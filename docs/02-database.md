> Exported from design plan v3 (2026-09-18). Source of truth: this docs/ folder; update docs before changing code.

# 二、数据库设计

## 2.1 ER 关系（MySQL 11 张表）

```
users ─┬─< resumes ─┬─< parsed_blocks
       │            ├─< diagnoses ─< findings
       │            ├─< match_reports ──────────┐
       │            └─< interview_sessions ─< interview_turns
       │                    ▲          ▲        │
       └─< jobs ────────────┴──────────┘        │
                                                (match_report_id)
skills      技能本体（自引用层级），向量在 Chroma
llm_calls   调用审计
```

## 2.2 建表 SQL

### ① users

```sql
CREATE TABLE users (
  id            BIGINT       PRIMARY KEY AUTO_INCREMENT,
  username      VARCHAR(50)  NOT NULL UNIQUE,
  email         VARCHAR(100) UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role          ENUM('seeker','admin') NOT NULL DEFAULT 'seeker',
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### ② resumes

```sql
CREATE TABLE resumes (
  id         BIGINT       PRIMARY KEY AUTO_INCREMENT,
  user_id    BIGINT       NOT NULL,
  parent_id  BIGINT       NULL COMMENT '版本链，本期恒为 NULL',
  version_no INT          NOT NULL DEFAULT 1,
  title      VARCHAR(200) NOT NULL COMMENT '原始文件名消毒后，仅展示',

  file_path  VARCHAR(500) NOT NULL COMMENT '相对路径 uploads/{user_id}/{uuid}.{ext}',
  file_type  ENUM('pdf','docx') NOT NULL,
  file_size  INT          NOT NULL,
  file_hash  CHAR(64)     NOT NULL,

  parse_status      ENUM('pending','parsing','success','failed') NOT NULL DEFAULT 'pending',
  parse_error       VARCHAR(100) COMMENT 'scanned_pdf / interrupted / exception:<msg>',
  layout_type       ENUM('single','double','sidebar','table','unknown') NOT NULL DEFAULT 'unknown' COMMENT '第 1 页判定；DOCX 恒 single',
  layout_confidence FLOAT   COMMENT '各页最小值；< 0.7 即存在 unknown 页 → LLM 兜底；DOCX 恒 1.0',
  layout_detail     JSON    COMMENT '[{page_no, layout_type, confidence, gap:[x0,x1]|null}]',
  used_llm_fallback BOOLEAN NOT NULL DEFAULT FALSE,
  page_count        INT     NULL COMMENT 'DOCX 为 NULL',
  ats_signals       JSON    COMMENT '{textboxes, drawings, images} 计数',

  full_text    MEDIUMTEXT COMMENT '★ 坐标系基准，解析后永不改变',
  structure    JSON       COMMENT '结构化结果，含 summary / skill_mentions',
  sections     JSON       COMMENT '[{type, title, char_start, char_end, confidence}]',
  is_corrected BOOLEAN    NOT NULL DEFAULT FALSE,
  corrected_at DATETIME,

  overall_score DECIMAL(5,2) COMMENT '最近一次成功诊断，同事务回写；人工纠正后置 NULL',
  is_deleted    BOOLEAN  NOT NULL DEFAULT FALSE,
  deleted_at    DATETIME NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  FOREIGN KEY (user_id)   REFERENCES users(id),
  FOREIGN KEY (parent_id) REFERENCES resumes(id) ON DELETE SET NULL,
  INDEX idx_user (user_id, is_deleted, updated_at),
  INDEX idx_hash (user_id, file_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

`structure` 结构（键名为本系统规范；每个条目带 `block_ids` 与由其推出的 char 区间）：

```json
{
  "basics":   { "name": "", "email": "", "phone": "", "location": "" },
  "summary":  { "text": "", "block_ids": [3], "char_start": 40, "char_end": 120 },
  "education":[ { "school": "", "major": "", "degree": "本科", "start": "2023-09", "end": "2027-06",
                  "block_ids": [5, 6], "char_start": 120, "char_end": 180 } ],
  "work":     [ { "company": "", "position": "", "kind": "internship",
                  "start": "2025-07", "end": null, "is_present": true,
                  "block_ids": [10, 11, 12], "char_start": 400, "char_end": 620,
                  "highlights": [ { "text": "<full_text 按 block_ids 切片，逐字原文>",
                                    "block_ids": [12], "char_start": 560, "char_end": 620 } ] } ],
  "projects": [ { "name": "", "role": "", "start": "", "end": "",
                  "tech_stack": [ { "name": "Spring Boot", "skill_id": 133 } ],
                  "block_ids": [], "char_start": 0, "char_end": 0, "highlights": [] } ],
  "skills":   [ { "name": "Spring Boot", "level": "熟悉", "skill_id": 133, "char_start": 900, "char_end": 911 } ],
  "awards":   [ ],
  "skill_mentions": [ { "skill_id": 133, "surface": "SpringBoot", "char_start": 880, "char_end": 890,
                        "section_type": "projects", "matched_by": "alias" } ]
}
```

> `basics` 本地正则抽取（不变量⑤）；`kind ∈ {work, internship, campus}`；日期 `YYYY-MM` / `YYYY` / null；`matched_by ∈ {alias, embedding}`。

### ③ parsed_blocks

```sql
CREATE TABLE parsed_blocks (
  id           BIGINT PRIMARY KEY AUTO_INCREMENT,
  resume_id    BIGINT NOT NULL,
  block_index  INT    NOT NULL COMMENT '★ 重建后的全局阅读顺序',
  page_no      INT    NOT NULL DEFAULT 1,
  column_index INT    NOT NULL DEFAULT 0 COMMENT '0=左栏/单栏 1=右栏 -1=跨栏行',
  x0 FLOAT NULL, y0 FLOAT NULL, x1 FLOAT NULL, y1 FLOAT NULL,   -- DOCX 为 NULL
  text      TEXT    NOT NULL,
  font_size FLOAT   NULL,
  is_bold   BOOLEAN NOT NULL DEFAULT FALSE,
  char_start INT NOT NULL COMMENT '相对 full_text，开区间',
  char_end   INT NOT NULL,
  FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE CASCADE,
  INDEX idx_order (resume_id, block_index),
  INDEX idx_char  (resume_id, char_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### ④ diagnoses

```sql
CREATE TABLE diagnoses (
  id        BIGINT PRIMARY KEY AUTO_INCREMENT,
  resume_id BIGINT NOT NULL,
  status    ENUM('pending','running','success','partial','failed','cancelled') NOT NULL DEFAULT 'pending'
            COMMENT 'partial = 成本预检截断了部分条目',
  error_msg VARCHAR(200),
  mode           ENUM('rule_only','llm_only','hybrid') NOT NULL DEFAULT 'hybrid',
  model_name     VARCHAR(50),
  prompt_version VARCHAR(20),
  job_title      VARCHAR(200) NULL,
  units_total    INT NOT NULL DEFAULT 0,
  units_skipped  INT NOT NULL DEFAULT 0,
  rule_finding_count  INT NOT NULL DEFAULT 0,
  llm_finding_count   INT NOT NULL DEFAULT 0 COMMENT '首轮产出总数 = 通过 + 未通过',
  hallucination_count INT NOT NULL DEFAULT 0 COMMENT '首轮 evidence_mismatch 数；拦截率 = 此 / llm_finding_count',
  schema_error_count  INT NOT NULL DEFAULT 0,
  overall_score       DECIMAL(5,2),
  score_detail        JSON COMMENT '{completeness, quantification, expression, consistency, ats}，无来源维度 null',
  token_input  INT NOT NULL DEFAULT 0,
  token_output INT NOT NULL DEFAULT 0,
  cost         DECIMAL(10,6) NOT NULL DEFAULT 0,
  started_at  DATETIME,
  finished_at DATETIME,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE CASCADE,
  INDEX idx_resume (resume_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### ⑤ findings

```sql
CREATE TABLE findings (
  id           BIGINT PRIMARY KEY AUTO_INCREMENT,
  diagnosis_id BIGINT NOT NULL,
  source    ENUM('rule','llm') NOT NULL,
  rule_code VARCHAR(50),
  risk_type VARCHAR(50),
  category  ENUM('completeness','quantification','expression','consistency','ats') NOT NULL,
  severity  ENUM('high','medium','low') NOT NULL,
  title       VARCHAR(200) NOT NULL,
  description TEXT,
  suggestion  TEXT,
  unit_id        VARCHAR(40) COMMENT '所属条目，如 work[0].highlights[2]',
  evidence_quote TEXT,
  char_start     INT,
  char_end       INT,
  page_no        INT  NULL,
  bbox           JSON NULL COMMENT '落库时由 parsed_blocks 映射；DOCX 为 NULL',
  verify_result ENUM('exact','fuzzy','failed') NOT NULL COMMENT '规则通道恒 exact；failed 行保留不展示',
  match_score   FLOAT,
  attempt_no    TINYINT NOT NULL DEFAULT 1 COMMENT '1=首轮，2/3=重试产出',
  rewrite JSON NULL COMMENT '{used_rag, rewritten, placeholders, changes, violation_count, created_at}',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (diagnosis_id) REFERENCES diagnoses(id) ON DELETE CASCADE,
  INDEX idx_diagnosis (diagnosis_id, severity),
  INDEX idx_verify    (diagnosis_id, verify_result)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### ⑥ jobs

```sql
CREATE TABLE jobs (
  id          BIGINT       PRIMARY KEY AUTO_INCREMENT,
  user_id     BIGINT       NULL COMMENT '模板岗位为 NULL',
  is_template BOOLEAN      NOT NULL DEFAULT FALSE COMMENT '由 jd_corpus 统计生成的通用岗位',
  title       VARCHAR(200) NOT NULL,
  company     VARCHAR(200) NULL,
  raw_text    TEXT         NOT NULL,
  requirements JSON COMMENT '[{id, req_type:hard|plus|soft, category:skill|education|experience|other, content, skill_id, weight}]',
  parse_status ENUM('pending','success','failed') NOT NULL DEFAULT 'pending',
  is_deleted BOOLEAN  NOT NULL DEFAULT FALSE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id),
  INDEX idx_user (user_id, is_deleted),
  INDEX idx_template (is_template)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### ⑦ match_reports

```sql
CREATE TABLE match_reports (
  id        BIGINT PRIMARY KEY AUTO_INCREMENT,
  resume_id BIGINT NOT NULL,
  job_id    BIGINT NOT NULL,
  status           ENUM('pending','running','success','failed') NOT NULL DEFAULT 'pending',
  error_msg        VARCHAR(200),
  overall_match    DECIMAL(5,2),
  passed           BOOLEAN NULL COMMENT 'overall_match >= SCREEN_THRESHOLD',
  dimension_scores JSON COMMENT '{skill, experience, education, project}',
  items            JSON COMMENT '[{requirement_id, content, status:hit|partial|miss, similarity, matched_evidence, char_start, char_end, match_path, matched_by, suggestion}]',
  gap_summary      TEXT,
  skill_gap_stats  JSON COMMENT '[{skill_id, name, jd_ratio, covered}]',
  use_reranker     BOOLEAN NOT NULL DEFAULT FALSE,
  cost             DECIMAL(10,6) NOT NULL DEFAULT 0,
  started_at  DATETIME,
  finished_at DATETIME,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE CASCADE,
  FOREIGN KEY (job_id)    REFERENCES jobs(id)    ON DELETE CASCADE,
  INDEX idx_resume_job (resume_id, job_id),
  INDEX idx_job        (job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### ⑧ skills

```sql
CREATE TABLE skills (
  id             BIGINT       PRIMARY KEY AUTO_INCREMENT,
  canonical_name VARCHAR(100) NOT NULL UNIQUE,
  category       VARCHAR(50),
  parent_id      BIGINT       NULL,
  level          INT          NOT NULL DEFAULT 0,
  aliases        JSON,
  description    VARCHAR(500),
  doc_freq       INT          NOT NULL DEFAULT 0 COMMENT 'JD 语料出现频次',
  created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (parent_id) REFERENCES skills(id) ON DELETE SET NULL,
  INDEX idx_category (category),
  INDEX idx_parent   (parent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

> M0 先放 100–200 条手写种子 CSV；M5 由 `build_ontology.py` 从 JD 语料扩充。

### ⑨ interview_sessions

```sql
CREATE TABLE interview_sessions (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id         BIGINT NOT NULL,
  resume_id       BIGINT NOT NULL,
  job_id          BIGINT NOT NULL,
  match_report_id BIGINT NULL,

  company_name  VARCHAR(200) NULL,
  extra_context MEDIUMTEXT   NULL COMMENT '用户粘贴的面经/公司介绍；>3000 字时切块进 Chroma interview_ctx',
  mode          ENUM('normal','practice') NOT NULL DEFAULT 'normal' COMMENT 'practice = 初筛未通过仍练习',

  status         ENUM('planned','in_progress','completed','abandoned') NOT NULL DEFAULT 'planned',
  current_round  ENUM('tech','hr') NULL,
  current_topic  INT NOT NULL DEFAULT 0,
  current_depth  TINYINT NOT NULL DEFAULT 0 COMMENT '0=主问 1/2=追问层',

  plan   JSON COMMENT '{topics:[{idx, round, intent, linked_type:finding|requirement|project|general, linked_id, budget, context_snippets[]}]}',
  report JSON COMMENT '{round_scores:{tech,hr}, overall, verdict, strengths[], weaknesses[], linked_findings[], turns_review[]}',

  model_name     VARCHAR(50),
  prompt_version VARCHAR(20),
  cost           DECIMAL(10,6) NOT NULL DEFAULT 0,
  cost_limit     DECIMAL(10,4) NOT NULL DEFAULT 0.3,

  started_at     DATETIME,
  finished_at    DATETIME,
  last_active_at DATETIME,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  FOREIGN KEY (user_id)         REFERENCES users(id),
  FOREIGN KEY (resume_id)       REFERENCES resumes(id)       ON DELETE CASCADE,
  FOREIGN KEY (job_id)          REFERENCES jobs(id)          ON DELETE CASCADE,
  FOREIGN KEY (match_report_id) REFERENCES match_reports(id) ON DELETE SET NULL,
  INDEX idx_user (user_id, created_at),
  INDEX idx_active (status, last_active_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### ⑩ interview_turns

```sql
CREATE TABLE interview_turns (
  id         BIGINT PRIMARY KEY AUTO_INCREMENT,
  session_id BIGINT NOT NULL,
  round      ENUM('tech','hr') NOT NULL,
  turn_no    INT     NOT NULL COMMENT '会话内全局序号',
  topic_idx  INT     NOT NULL,
  depth      TINYINT NOT NULL DEFAULT 0,

  question      TEXT NOT NULL,
  question_meta JSON COMMENT '{intent, linked_type, linked_id, rubric_focus[]}',
  answer        TEXT NULL,
  answered_at   DATETIME NULL,

  evaluation JSON NULL COMMENT '{scores:{...}, evidence:[{quote, char_start, char_end, verify_result}], feedback, better_answer, decision:followup|next|end_round}',
  cost       DECIMAL(10,6) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  FOREIGN KEY (session_id) REFERENCES interview_sessions(id) ON DELETE CASCADE,
  INDEX idx_session (session_id, turn_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

> 评估中的 `evidence` 是从**用户回答文本**里逐字引用并经 `locate_span` 校验的（不变量⑥）；校验失败的引用丢弃，评分若无任何有效引用则降为"证据不足"并只给中性分。

### ⑪ llm_calls

```sql
CREATE TABLE llm_calls (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  scene    VARCHAR(50) NOT NULL COMMENT 'relayout/section/structure/diagnose/jd_parse/rewrite/gap/iv_plan/iv_eval/iv_ask/iv_report/embed/rerank',
  ref_type VARCHAR(30) COMMENT 'resume/diagnosis/finding/match_report/interview_session/interview_turn',
  ref_id   BIGINT,
  provider       VARCHAR(30),
  model_name     VARCHAR(50) NOT NULL,
  model_version  VARCHAR(64) NULL COMMENT 'response_metadata.system_fingerprint',
  prompt_version VARCHAR(20),
  run_id         VARCHAR(36) NULL COMMENT '评测批次；线上为 NULL',
  token_input  INT NOT NULL DEFAULT 0,
  token_output INT NOT NULL DEFAULT 0,
  cost         DECIMAL(10,6) NOT NULL DEFAULT 0,
  latency_ms   INT,
  cache_hit BOOLEAN NOT NULL DEFAULT FALSE,
  success   BOOLEAN NOT NULL DEFAULT TRUE,
  error_msg VARCHAR(500),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_scene (scene, created_at),
  INDEX idx_ref   (ref_type, ref_id),
  INDEX idx_run   (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 2.3 Chroma（4 个 collection）

```
skills         技能本体向量      ~5,000    metadata {skill_id, category, level}
cases          优秀描述案例      1,000+    metadata {job_category, tech_stack[], source}    仅公开数据
jd_corpus      JD 语料           1,000+    metadata {job_title, category}
interview_ctx  面试附加材料切块   按需      metadata {session_id, chunk_idx}；会话结束即删
```

`scripts/seed.py` 幂等重建前三个 collection、skills 表、岗位模板；`uploads/`、`chroma/`、`.env` 进 `.gitignore`。

## 2.4 设计说明（v3 变更点）

| 决策 | 理由 |
|---|---|
| 去掉 screenings / screening_items，加 interview_sessions / interview_turns | 模拟面试替换 HR 端；表数不变 |
| 面试状态（round / topic / depth）存 DB，不用 LangGraph checkpoint | 面试跨 HTTP 请求，DB 就是检查点，刷新可续 |
| 计划与报告存 JSON | 只整体读写 |
| 评分 evidence 走同一个 `locate_span` | 一个反幻觉机制，三处复用 |
| `jobs.is_template` | 无具体 JD 的用户也能面试 |
| 其余（不变量、adopt 移除、checkpoint 不启用、bbox 可空…）沿用 v2 | |
