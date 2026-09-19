-- 迁移 001（2026-09-19）：技能匹配改为「词典 + LLM 判定」
-- 仅当你的库是用旧版 schema.sql 建的才需要执行；全新建库直接用最新 schema.sql，不用执行本文件。
-- 在 MySQL 中执行一次。两张表目前都是空表，不涉及数据丢失。

USE `resume_ai`;

-- skills：去掉层级与统计字段，变为扁平同义词词典
ALTER TABLE skills DROP FOREIGN KEY skills_ibfk_1;
ALTER TABLE skills
  DROP INDEX idx_parent,
  DROP COLUMN parent_id,
  DROP COLUMN level,
  DROP COLUMN description,
  DROP COLUMN doc_freq,
  MODIFY category VARCHAR(50) NULL COMMENT 'language/backend/frontend/database/devops/ai/data/tool',
  MODIFY aliases JSON NULL COMMENT '不含规范名本身';

-- match_reports：去掉 reranker / 技能分布，加入匹配消融字段
ALTER TABLE match_reports
  DROP COLUMN skill_gap_stats,
  DROP COLUMN use_reranker,
  ADD COLUMN diagnosis_id BIGINT NULL COMMENT '同一次投递产生的诊断，未通过说明要用' AFTER gap_summary,
  ADD COLUMN mode ENUM('dict_only','llm_fulltext','llm_rag','hybrid') NOT NULL DEFAULT 'hybrid' AFTER diagnosis_id,
  ADD COLUMN model_name VARCHAR(50) NULL AFTER mode,
  ADD COLUMN prompt_version VARCHAR(20) NULL AFTER model_name,
  ADD COLUMN llm_item_count INT NOT NULL DEFAULT 0 COMMENT 'LLM 判定的要求项数' AFTER prompt_version,
  ADD COLUMN hallucination_count INT NOT NULL DEFAULT 0 COMMENT '其中引用无法定位的条数' AFTER llm_item_count,
  ADD INDEX diagnosis_id (diagnosis_id),   -- 与全新建库时 MySQL 为外键自动生成的索引同名
  ADD CONSTRAINT match_reports_ibfk_3 FOREIGN KEY (diagnosis_id) REFERENCES diagnoses(id) ON DELETE SET NULL;

-- findings.rewrite：注释补充 used_rerank（仅注释变化）
ALTER TABLE findings
  MODIFY rewrite JSON NULL COMMENT '{used_rag, used_rerank, rewritten, placeholders, changes, violation_count, created_at}';
