-- 智能求职辅助系统 建库建表脚本（MySQL 8.0）
-- 本文件由 scripts/dump_schema.py 从 app/models.py 自动生成，请勿手改。
--
-- 手动建表（在全新的库上执行一次；CREATE INDEX 不可重复执行）：
--   mysql -uroot -p < backend/sql/schema.sql
-- （也可以不执行：后端首次启动会自动建库建表，效果相同）

CREATE DATABASE IF NOT EXISTS `resume_ai` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `resume_ai`;

-- llm_calls
CREATE TABLE IF NOT EXISTS llm_calls (
  id BIGINT NOT NULL AUTO_INCREMENT, 
  scene VARCHAR(50) NOT NULL, 
  ref_type VARCHAR(30), 
  ref_id BIGINT, 
  provider VARCHAR(30), 
  model_name VARCHAR(50) NOT NULL, 
  model_version VARCHAR(64) COMMENT 'system_fingerprint', 
  prompt_version VARCHAR(20), 
  run_id VARCHAR(36) COMMENT '评测批次；线上为 NULL', 
  token_input INTEGER NOT NULL DEFAULT '0', 
  token_output INTEGER NOT NULL DEFAULT '0', 
  cost NUMERIC(10, 6) NOT NULL DEFAULT '0', 
  latency_ms INTEGER, 
  cache_hit BOOL NOT NULL DEFAULT 0, 
  success BOOL NOT NULL DEFAULT 1, 
  error_msg VARCHAR(500), 
  created_at DATETIME NOT NULL DEFAULT now(), 
  PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4;
CREATE INDEX idx_ref ON llm_calls (ref_type, ref_id);
CREATE INDEX idx_run ON llm_calls (run_id);
CREATE INDEX idx_scene ON llm_calls (scene, created_at);

-- skills
CREATE TABLE IF NOT EXISTS skills (
  id BIGINT NOT NULL AUTO_INCREMENT, 
  canonical_name VARCHAR(100) NOT NULL, 
  category VARCHAR(50), 
  parent_id BIGINT COMMENT '上位技能：Spring Boot ⊂ Spring ⊂ Java', 
  level INTEGER NOT NULL DEFAULT '0', 
  aliases JSON, 
  description VARCHAR(500), 
  doc_freq INTEGER NOT NULL COMMENT 'JD 语料出现频次' DEFAULT '0', 
  created_at DATETIME NOT NULL DEFAULT now(), 
  PRIMARY KEY (id), 
  UNIQUE (canonical_name), 
  FOREIGN KEY(parent_id) REFERENCES skills (id) ON DELETE SET NULL
)ENGINE=InnoDB CHARSET=utf8mb4;
CREATE INDEX idx_category ON skills (category);
CREATE INDEX idx_parent ON skills (parent_id);

-- users
CREATE TABLE IF NOT EXISTS users (
  id BIGINT NOT NULL AUTO_INCREMENT, 
  username VARCHAR(50) NOT NULL, 
  email VARCHAR(100), 
  password_hash VARCHAR(255) NOT NULL, 
  `role` ENUM('seeker','admin') NOT NULL DEFAULT 'seeker', 
  created_at DATETIME NOT NULL DEFAULT now(), 
  PRIMARY KEY (id), 
  UNIQUE (username), 
  UNIQUE (email)
)ENGINE=InnoDB CHARSET=utf8mb4;

-- jobs
CREATE TABLE IF NOT EXISTS jobs (
  id BIGINT NOT NULL AUTO_INCREMENT, 
  user_id BIGINT COMMENT '模板岗位为 NULL', 
  is_template BOOL NOT NULL DEFAULT 0, 
  title VARCHAR(200) NOT NULL, 
  company VARCHAR(200), 
  raw_text TEXT NOT NULL, 
  requirements JSON COMMENT '[{id, req_type, category, content, skill_id, weight}]', 
  parse_status ENUM('pending','success','failed') NOT NULL DEFAULT 'pending', 
  is_deleted BOOL NOT NULL DEFAULT 0, 
  created_at DATETIME NOT NULL DEFAULT now(), 
  PRIMARY KEY (id), 
  FOREIGN KEY(user_id) REFERENCES users (id)
)ENGINE=InnoDB CHARSET=utf8mb4;
CREATE INDEX idx_job_user ON jobs (user_id, is_deleted);
CREATE INDEX idx_template ON jobs (is_template);

-- resumes
CREATE TABLE IF NOT EXISTS resumes (
  id BIGINT NOT NULL AUTO_INCREMENT, 
  user_id BIGINT NOT NULL, 
  parent_id BIGINT COMMENT '版本链，本期恒为 NULL', 
  version_no INTEGER NOT NULL DEFAULT '1', 
  title VARCHAR(200) NOT NULL COMMENT '原始文件名消毒后，仅展示', 
  file_path VARCHAR(500) NOT NULL COMMENT '相对路径 uploads/{user_id}/{uuid}.{ext}', 
  file_type ENUM('pdf','docx') NOT NULL, 
  file_size INTEGER NOT NULL, 
  file_hash CHAR(64) NOT NULL COMMENT 'SHA-256', 
  parse_status ENUM('pending','parsing','success','failed') NOT NULL DEFAULT 'pending', 
  parse_error VARCHAR(100) COMMENT 'scanned_pdf / interrupted / exception:<msg>', 
  layout_type ENUM('single','double','sidebar','table','unknown') NOT NULL COMMENT '第 1 页判定；DOCX 恒 single' DEFAULT 'unknown', 
  layout_confidence FLOAT COMMENT '各页最小值；<0.7 触发 LLM 兜底', 
  layout_detail JSON COMMENT '[{page_no, layout_type, confidence, gap}]', 
  used_llm_fallback BOOL NOT NULL DEFAULT 0, 
  page_count INTEGER COMMENT 'DOCX 为 NULL', 
  ats_signals JSON COMMENT '{textboxes, drawings, images}', 
  full_text MEDIUMTEXT COMMENT '坐标系基准，解析后永不改变', 
  structure JSON COMMENT '结构化结果，含 summary / skill_mentions', 
  sections JSON COMMENT '[{type, title, char_start, char_end, confidence}]', 
  is_corrected BOOL NOT NULL DEFAULT 0, 
  corrected_at DATETIME, 
  overall_score NUMERIC(5, 2) COMMENT '最近一次成功诊断，同事务回写', 
  is_deleted BOOL NOT NULL DEFAULT 0, 
  deleted_at DATETIME, 
  created_at DATETIME NOT NULL DEFAULT now(), 
  updated_at DATETIME NOT NULL DEFAULT now(), 
  PRIMARY KEY (id), 
  FOREIGN KEY(user_id) REFERENCES users (id), 
  FOREIGN KEY(parent_id) REFERENCES resumes (id) ON DELETE SET NULL
)ENGINE=InnoDB CHARSET=utf8mb4;
CREATE INDEX idx_hash ON resumes (user_id, file_hash);
CREATE INDEX idx_user ON resumes (user_id, is_deleted, updated_at);

-- diagnoses
CREATE TABLE IF NOT EXISTS diagnoses (
  id BIGINT NOT NULL AUTO_INCREMENT, 
  resume_id BIGINT NOT NULL, 
  status ENUM('pending','running','success','partial','failed','cancelled') NOT NULL COMMENT 'partial = 成本预检截断了部分条目' DEFAULT 'pending', 
  error_msg VARCHAR(200), 
  mode ENUM('rule_only','llm_only','hybrid') NOT NULL DEFAULT 'hybrid', 
  model_name VARCHAR(50), 
  prompt_version VARCHAR(20), 
  job_title VARCHAR(200), 
  units_total INTEGER NOT NULL DEFAULT '0', 
  units_skipped INTEGER NOT NULL DEFAULT '0', 
  rule_finding_count INTEGER NOT NULL DEFAULT '0', 
  llm_finding_count INTEGER NOT NULL DEFAULT '0', 
  hallucination_count INTEGER NOT NULL DEFAULT '0', 
  schema_error_count INTEGER NOT NULL DEFAULT '0', 
  overall_score NUMERIC(5, 2), 
  score_detail JSON, 
  token_input INTEGER NOT NULL DEFAULT '0', 
  token_output INTEGER NOT NULL DEFAULT '0', 
  cost NUMERIC(10, 6) NOT NULL DEFAULT '0', 
  started_at DATETIME, 
  finished_at DATETIME, 
  created_at DATETIME NOT NULL DEFAULT now(), 
  PRIMARY KEY (id), 
  FOREIGN KEY(resume_id) REFERENCES resumes (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4;
CREATE INDEX idx_resume ON diagnoses (resume_id, created_at);

-- match_reports
CREATE TABLE IF NOT EXISTS match_reports (
  id BIGINT NOT NULL AUTO_INCREMENT, 
  resume_id BIGINT NOT NULL, 
  job_id BIGINT NOT NULL, 
  status ENUM('pending','running','success','failed') NOT NULL DEFAULT 'pending', 
  error_msg VARCHAR(200), 
  overall_match NUMERIC(5, 2), 
  passed BOOL COMMENT 'overall_match >= SCREEN_THRESHOLD', 
  dimension_scores JSON, 
  items JSON COMMENT '逐项匹配明细', 
  gap_summary TEXT, 
  skill_gap_stats JSON, 
  use_reranker BOOL NOT NULL DEFAULT 0, 
  cost NUMERIC(10, 6) NOT NULL DEFAULT '0', 
  started_at DATETIME, 
  finished_at DATETIME, 
  created_at DATETIME NOT NULL DEFAULT now(), 
  PRIMARY KEY (id), 
  FOREIGN KEY(resume_id) REFERENCES resumes (id) ON DELETE CASCADE, 
  FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4;
CREATE INDEX idx_job ON match_reports (job_id);
CREATE INDEX idx_resume_job ON match_reports (resume_id, job_id);

-- parsed_blocks
CREATE TABLE IF NOT EXISTS parsed_blocks (
  id BIGINT NOT NULL AUTO_INCREMENT, 
  resume_id BIGINT NOT NULL, 
  block_index INTEGER NOT NULL COMMENT '重建后的全局阅读顺序', 
  page_no INTEGER NOT NULL DEFAULT '1', 
  column_index INTEGER NOT NULL COMMENT '0=左栏/单栏 1=右栏 -1=跨栏行' DEFAULT '0', 
  x0 FLOAT, 
  y0 FLOAT, 
  x1 FLOAT, 
  y1 FLOAT, 
  text TEXT NOT NULL, 
  font_size FLOAT, 
  is_bold BOOL NOT NULL DEFAULT 0, 
  char_start INTEGER NOT NULL, 
  char_end INTEGER NOT NULL, 
  PRIMARY KEY (id), 
  FOREIGN KEY(resume_id) REFERENCES resumes (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4;
CREATE INDEX idx_char ON parsed_blocks (resume_id, char_start);
CREATE INDEX idx_order ON parsed_blocks (resume_id, block_index);

-- findings
CREATE TABLE IF NOT EXISTS findings (
  id BIGINT NOT NULL AUTO_INCREMENT, 
  diagnosis_id BIGINT NOT NULL, 
  source ENUM('rule','llm') NOT NULL, 
  rule_code VARCHAR(50) COMMENT '规则通道', 
  risk_type VARCHAR(50) COMMENT 'LLM 通道', 
  category ENUM('completeness','quantification','expression','consistency','ats') NOT NULL, 
  severity ENUM('high','medium','low') NOT NULL, 
  title VARCHAR(200) NOT NULL, 
  description TEXT, 
  suggestion TEXT, 
  unit_id VARCHAR(40) COMMENT '如 work[0].highlights[2]', 
  evidence_quote TEXT, 
  char_start INTEGER, 
  char_end INTEGER, 
  page_no INTEGER, 
  bbox JSON COMMENT '落库时由 parsed_blocks 映射；DOCX 为 NULL', 
  verify_result ENUM('exact','fuzzy','failed') NOT NULL, 
  match_score FLOAT, 
  attempt_no SMALLINT NOT NULL DEFAULT '1', 
  rewrite JSON COMMENT '{used_rag, rewritten, placeholders, changes, violation_count, created_at}', 
  created_at DATETIME NOT NULL DEFAULT now(), 
  PRIMARY KEY (id), 
  FOREIGN KEY(diagnosis_id) REFERENCES diagnoses (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4;
CREATE INDEX idx_diagnosis ON findings (diagnosis_id, severity);
CREATE INDEX idx_verify ON findings (diagnosis_id, verify_result);

-- interview_sessions
CREATE TABLE IF NOT EXISTS interview_sessions (
  id BIGINT NOT NULL AUTO_INCREMENT, 
  user_id BIGINT NOT NULL, 
  resume_id BIGINT NOT NULL, 
  job_id BIGINT NOT NULL, 
  match_report_id BIGINT, 
  company_name VARCHAR(200), 
  extra_context MEDIUMTEXT COMMENT '用户粘贴的面经/公司介绍', 
  mode ENUM('normal','practice') NOT NULL DEFAULT 'normal', 
  status ENUM('planned','in_progress','completed','abandoned') NOT NULL DEFAULT 'planned', 
  current_round ENUM('tech','hr'), 
  current_topic INTEGER NOT NULL DEFAULT '0', 
  current_depth SMALLINT NOT NULL DEFAULT '0', 
  plan JSON, 
  report JSON, 
  model_name VARCHAR(50), 
  prompt_version VARCHAR(20), 
  cost NUMERIC(10, 6) NOT NULL DEFAULT '0', 
  cost_limit NUMERIC(10, 4) NOT NULL DEFAULT '0.3', 
  started_at DATETIME, 
  finished_at DATETIME, 
  last_active_at DATETIME, 
  created_at DATETIME NOT NULL DEFAULT now(), 
  PRIMARY KEY (id), 
  FOREIGN KEY(user_id) REFERENCES users (id), 
  FOREIGN KEY(resume_id) REFERENCES resumes (id) ON DELETE CASCADE, 
  FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE, 
  FOREIGN KEY(match_report_id) REFERENCES match_reports (id) ON DELETE SET NULL
)ENGINE=InnoDB CHARSET=utf8mb4;
CREATE INDEX idx_active ON interview_sessions (status, last_active_at);
CREATE INDEX idx_iv_user ON interview_sessions (user_id, created_at);

-- interview_turns
CREATE TABLE IF NOT EXISTS interview_turns (
  id BIGINT NOT NULL AUTO_INCREMENT, 
  session_id BIGINT NOT NULL, 
  round ENUM('tech','hr') NOT NULL, 
  turn_no INTEGER NOT NULL COMMENT '会话内全局序号', 
  topic_idx INTEGER NOT NULL, 
  depth SMALLINT NOT NULL COMMENT '0=主问 1/2=追问' DEFAULT '0', 
  question TEXT NOT NULL, 
  question_meta JSON, 
  answer TEXT, 
  answered_at DATETIME, 
  evaluation JSON COMMENT '{scores, evidence[], feedback, better_answer, decision}', 
  cost NUMERIC(10, 6) NOT NULL DEFAULT '0', 
  created_at DATETIME NOT NULL DEFAULT now(), 
  PRIMARY KEY (id), 
  FOREIGN KEY(session_id) REFERENCES interview_sessions (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4;
CREATE INDEX idx_session ON interview_turns (session_id, turn_no);

-- MySQL 专有补充（幂等）
ALTER TABLE resumes MODIFY updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP;
