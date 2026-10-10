# 二、数据库设计

MySQL 8.0，12 张表。**完整建表语句以 `backend/sql/schema.sql` 为准**：它由 `scripts/dump_schema.py` 从 `backend/app/models.py` 生成（改表先改 models.py，再重新生成），`tests/test_schema_sync.py` 检查两者一致。本章不再抄建表语句，只写每张表的用途与要点、外键关系、JSON 字段结构和预留字段。

通用约定：

- 所有 `char_start / char_end` 都是左闭右开区间 `[start, end)`。没有特别说明的，都相对 `resumes.full_text`；JD 要求项的区间相对 `jobs.raw_text`，面试评分依据的区间相对这一题的回答文本。
- JSON 字段只整体读写，不按里面的键查询。
- 枚举存为 MySQL ENUM；时间列为 DATETIME（本地时间）。

## 2.1 表与外键关系

一次投递 = `match_reports` 一行（投递 id 就是它的 id），同时建一条 `diagnoses`，由 `match_reports.diagnosis_id` 指过去；模拟面试挂在投递下面（`interview_sessions.match_report_id`）。

```
users ─┬─< resumes ─┬─< parsed_blocks
       │            ├─< diagnoses ─< findings
       │            ├─< match_reports（投递）>── jobs
       │            └─< interview_sessions ─< interview_turns
       ├─< jobs（内置模板 user_id 为 NULL）
       └─< interview_sessions
另有两条：match_reports.diagnosis_id → diagnoses；interview_sessions.match_report_id → match_reports
skills（技能词典）、llm_calls（调用审计）不建外键
```

| 外键 | 指向 | 父行被删时 |
|---|---|---|
| `resumes.user_id` | users | 不允许删（默认 RESTRICT） |
| `resumes.parent_id` | resumes | 置 NULL（预留，见 2.4） |
| `jobs.user_id` | users（模板为 NULL） | 不允许删 |
| `parsed_blocks.resume_id` | resumes | 级联删除 |
| `diagnoses.resume_id` | resumes | 级联删除 |
| `findings.diagnosis_id` | diagnoses | 级联删除 |
| `match_reports.resume_id` | resumes | 级联删除 |
| `match_reports.job_id` | jobs | 级联删除 |
| `match_reports.diagnosis_id` | diagnoses | 置 NULL |
| `interview_sessions.user_id` | users | 不允许删 |
| `interview_sessions.resume_id` | resumes | 级联删除 |
| `interview_sessions.job_id` | jobs | 级联删除 |
| `interview_sessions.match_report_id` | match_reports | 置 NULL |
| `interview_turns.session_id` | interview_sessions | 级联删除 |

简历和岗位在业务上都是软删除（`is_deleted`），级联只在物理删除时生效。比如直接在库里删掉一份岗位模板，会连带删掉投给它的投递和面试，所以模板只按标题更新，不删了重插。

## 2.2 各表要点

### ① users

账号。`username`、`email` 唯一；`password_hash` 是 bcrypt 哈希；`role` 取 seeker / admin，注册时一律是 seeker。admin 只有一个：服务启动时按 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 建（已经有了就不动，密码可能在页面上改过）；这个用户名别人注册不了。

### ② resumes

一份上传的简历和它的解析结果。

- **文件**：`file_path` 是相对 `DATA_DIR` 的路径 `uploads/{user_id}/{uuid}.pdf`；`title` 是消毒后的原文件名（或上传时另给的标题），只用于展示；`file_hash`（SHA-256）用来去重：同一用户重复上传同一文件时复用这条记录（规则见 03 的 POST /resumes）。`page_count` 上传校验时就写入。
- **解析状态**：`parse_status` 为 pending → parsing → success / failed；失败原因 `parse_error` 取 `scanned_pdf`（扫描件）/ `encrypted_pdf` / `llm_failed` / `llm_unavailable`（解析时模型服务调不通）/ `interrupted`（服务重启打断）/ `exception:<异常类型>`。
- **版面**：`layout_type` 是第 1 页的判定（single / double / sidebar / table / unknown）；`layout_confidence` 取各页最小值，低于 0.7 表示有规则拿不准的页（不做大模型兜底，见 04-design 4.8）；`layout_detail` 是逐页明细（2.3）。
- **内容**：`full_text` 是坐标系基准，解析完成后不再改变（00-overview 不变量①）；`structure`、`sections` 的结构见 2.3。
- `overall_score`：最近一次成功诊断的总分，和诊断结果在同一事务里回写，列表页直接用。
- **软删除**：`is_deleted` / `deleted_at`。删除后对用户不可见，文件和数据先保留（到期物理删除还没做）。

### ③ parsed_blocks

解析出的文本块，`block_index` 是重建后的全局阅读顺序；每块满足 `full_text[char_start:char_end] == text`（不变量②）。`column_index`：0 = 左栏或单栏，1 = 右栏，-1 = 跨栏行。`x0 / y0 / x1 / y1` 是块在 PDF 页面上的坐标，findings 落库时用它算 `page_no` / `bbox`（前端高亮按 char 区间在 full_text 上定位，不用坐标）。重新解析时整批删掉重写。

### ④ diagnoses

一次简历诊断，由投递触发（一次投递一条）。

- `status`：pending → running → success / partial / failed。partial 表示成本预检截掉了部分条目（`units_skipped > 0`），结果可用但不完整。同一份简历同时只能有一个诊断在跑。
- `mode`：rule_only / llm_only / hybrid，是消融实验的开关；`model_name`、`prompt_version` 记下用的模型和提示词版本；`job_title` 是这次投的岗位名。
- 统计只算首轮（`findings.attempt_no = 1`）：`llm_finding_count` 是模型首轮产出的问题数（通过 + 被拦截），`hallucination_count` 是其中证据定位失败、被拦截的条数，两者之比就是拦截率；`schema_error_count` 是模型输出不合格式的次数。
- `score_detail`：五个维度的分（2.3）；`token_input / token_output` 从 llm_calls 汇总；`cost` 单位为元。

### ⑤ findings

诊断出的一条问题。

- `source`：rule / llm。规则通道填 `rule_code`，模型通道填 `risk_type`；`category` 是五个维度之一，`severity` 取 high / medium / low。
- 溯源：`unit_id` 是所属条目（如 `work[0].highlights[2]`），`evidence_quote` 加 char 区间是原文依据；`page_no`、`bbox`（`[x0, y0, x1, y1]`）在落库时由 parsed_blocks 映射出来。
- `verify_result`：exact / fuzzy / failed，规则通道恒为 exact。failed 的行保留但不展示，评测统计拦截率要用。`match_score` 是定位时的相似度。
- `attempt_no`：1 = 首轮，2、3 = 带着原因重试后的产出。
- `rewrite`：点开这条时现场生成的具体建议（2.3），没生成过为 NULL。

### ⑥ jobs

岗位：用户粘贴的 JD，或内置模板（`is_template = 1`，`user_id` 为 NULL）。

- `domain`：求职方向，取 `app/domains` 的 key（cs / ops / finance / general），决定 JD 解析、诊断、匹配、建议、面试用哪套提示词（04-design 4.16）。
- `raw_text` 是清洗后的 JD 原文，`requirements` 里的区间相对它；`requirements` 的结构见 2.3。
- `parse_status`：JD 同步解析，失败就不保存，所以目前只会写 success（2.4）。
- 软删除 `is_deleted`；模板不能删。

### ⑦ match_reports

一次投递的匹配报告，也就是投递本身。

- `status`：pending → running → success / failed。同一份简历对同一个岗位同时只能有一个在跑。`error_msg` 是给开发者看的技术报错；给用户看的失败原因在读取时组装（`apply_service.failure_of`）。
- `overall_match`：0–100 的加权匹配度；`passed` = `overall_match ≥ SCREEN_THRESHOLD`（默认 60）。
- `dimension_scores`：`{skill, education, experience, other}`，按要求项类别分组算的匹配度，JD 里没有这类要求的为 null。
- `items`：逐条要求的判定明细（2.3）。里面冗余存了要求的内容，岗位后来被删，报告照样读得懂。
- `mode`：dict_only / llm_fulltext / hybrid，匹配消融的开关；`llm_item_count` 是交给模型判定的要求项数，`hallucination_count` 是其中引用无法定位的条数。

### ⑧ skills

扁平的技能同义词词典，只回答「这个词是不是某个技能的另一种写法」。技能之间的上下位关系（Spring Boot 属于 Java 生态）不建树，交给模型判断。`canonical_name` 唯一，`aliases` 不含规范名本身，`category` 如 language / backend / frontend / database / ai / ops 等。数据来源 `data/skills_seed.csv`（手写，241 条：计算机 155、运营 51、财会 35）。简历解析和技能词典不分方向。

### ⑨ interview_sessions

一场模拟面试，挂在一次投递下面（`match_report_id`），`resume_id`、`job_id` 也冗余存一份。

- `mode`：normal / practice。初筛没过的一律 practice，过了的也可以主动选 practice。
- `status`：planned（话题已定、还没开始）→ in_progress → completed / abandoned。很久没动静（`INTERVIEW_IDLE_HOURS`，默认 24 小时）的面试在服务启动时扫一次、之后每小时扫一次，按已答的题出报告（不调模型写总结），标成 abandoned。
- 只做一轮专业面（计算机方向叫技术面、运营方向叫运营面、财会金融和「其他」叫专业面），`current_round` 恒为 tech。`current_topic` 是正在问的话题 idx（从 0 起），`current_depth` 为 0 表示主问题、1 表示追问。
- `company_name` 默认取岗位的公司名；`extra_context` 是用户贴的面经或公司介绍，超过 3000 字时切段进 Chroma（2.5）。
- `cost` / `cost_limit`：本场累计花费和上限（元，默认 0.3）。
- 本表和 interview_turns 是面试进度的权威来源。图 B 另用 SQLite 检查点（`checkpoints.sqlite`）续跑，检查点丢了就按这两张表重建（06-workflows 6.3）。`plan`、`report` 的结构见 2.3。

### ⑩ interview_turns

一问一答。`turn_no` 是会话内的全局序号；`topic_idx` 是所属话题，`depth` 为 0 表示主问题，1 起是第几次追问（上限 `INTERVIEW_MAX_FOLLOWUP`，默认 1）；`round` 恒为 tech；`question_meta` 为 `{label, source}`。`answer` 为 NULL 表示还没答，跳过时是空串；提交回答用条件更新（`answered_at IS NULL`），同一题只能答一次。`evaluation` 见 2.3。

### ⑪ llm_calls

每次模型调用一行审计，命中缓存的、失败的也记。

- `scene`：section / structure / diagnose / jd_parse / match / rewrite / gap / interview_plan / interview_ask / interview_eval / interview_report / embed / rerank。
- `ref_type` + `ref_id` 指向业务记录（resume / job / diagnosis / match_report / finding / interview），不建外键。
- `model_version` 取响应里的 system_fingerprint；`run_id` 是评测批次号，线上调用为 NULL；`cache_hit`、`success`、`error_msg`、`latency_ms`、token 数和 `cost` 用于成本统计和评测。

### ⑫ llm_providers

管理端保存的模型配置，一行一份，`purpose` 分两种：

- `chat`（对话模型）：可以存几家，最多一行 `is_active = 1`。`kind`（预设：deepseek / siliconflow / bailian / zhipu / moonshot / custom，限流分桶和 `llm_calls.provider` 用它）、`name`、`base_url`（OpenAI 兼容接口的地址）、`model`、`price_in` / `price_out`（元 / 百万 token，估算花费用）。
- `retrieval`（检索用的向量 + 重排）：只有一份，存了就是启用。`model` 是向量模型名，`rerank_model` 是重排模型名，单价恒为 0。

API Key 不存明文：`api_key_enc` 是 Fernet 加密后的（钥匙从 `JWT_SECRET` 派生，`JWT_SECRET` 换了就解不开、要重新填），`key_hint` 另存一份「开头 3 位 + 后 4 位」给页面看，列表不用解密。
没有启用的就用 `.env` 里的配置（`llm/provider.py`）。和别的表没有外键。

## 2.3 JSON 字段结构

### resumes.structure

键名是本系统自己定的。每个条目带 `block_ids`，以及由它推出的 char 区间（首尾块之间的连续一段）。

```json
{
  "basics":   { "name": "", "email": "", "phone": "", "location": "" },
  "summary":  { "text": "", "block_ids": [3], "char_start": 40, "char_end": 120 },
  "education":[ { "school": "", "major": "", "degree": "本科", "start": "2023-09", "end": "2027-06", "is_present": false,
                  "block_ids": [5, 6], "char_start": 120, "char_end": 180 } ],
  "work":     [ { "name": "<公司或组织>", "role": "", "kind": "internship",
                  "tech_stack": [ { "name": "Redis", "skill_id": 40 } ],
                  "start": "2025-07", "end": null, "is_present": true,
                  "block_ids": [10, 11, 12], "char_start": 400, "char_end": 620,
                  "highlights": [ { "text": "<full_text 按 block_ids 切片，逐字原文>",
                                    "block_ids": [12], "char_start": 560, "char_end": 620 } ] } ],
  "projects": [ { "name": "", "role": "", "tech_stack": [ { "name": "Spring Boot", "skill_id": 133 } ],
                  "start": null, "end": null, "is_present": false,
                  "block_ids": [], "char_start": 0, "char_end": 0, "highlights": [] } ],
  "skills":   [ { "name": "Spring Boot", "level": "熟悉", "skill_id": 133, "block_ids": [20], "char_start": 900, "char_end": 911 } ],
  "awards":   [ { "name": "", "start": "2024-11", "end": null, "is_present": false, "block_ids": [], "char_start": 0, "char_end": 0 } ],
  "skill_mentions": [ { "skill_id": 133, "surface": "SpringBoot", "char_start": 880, "char_end": 890,
                        "section_type": "projects", "matched_by": "dict" } ],
  "extraction_errors": [ "projects: 不是合法的 JSON" ]
}
```

- `basics` 在本地用正则抽取，不发给模型（不变量⑤）。没有自我评价章节时 `summary` 为 null。
- `work` 和 `projects` 结构相同，`work` 多一个 `kind`（work / internship / campus）。`highlights[].text` 是从原文切出来的，不用模型写的文字。
- 日期是 `YYYY-MM`、`YYYY` 或 null。`skill_id` 只有词典里有的技能才有，否则为 null。`skill_mentions.matched_by` 目前恒为 dict（同义词词典命中）。
- `extraction_errors`：章节归类（`section: …`）或某个章节抽取（`projects: …`）失败的原因。这类失败不算整体解析失败，其余部分照常可用，原因留在这里供排查。

### resumes.sections

一项一个章节，字段同 `schemas.SectionOut`：

| 键 | 含义 |
|---|---|
| `type` | basics / summary / education / work / projects / skills / awards / other |
| `kind` | 只有 work 才有：work / internship / campus；其余为 null |
| `title` | 标题原文；没有标题的段（如开头的基本信息）为 "" |
| `block_start` / `block_end` | 章节的首块和末块（闭区间，含标题块） |
| `char_start` / `char_end` | 章节在 full_text 里的区间 |
| `content_start` | 正文（标题之后）的起点；没有正文时等于 `char_end` |
| `confidence` | 0–1 |
| `matched_by` | dict（词典）/ feature / style / llm / implicit（没有标题块：基本信息、从开头段切出来的教育、整篇无标题） |
| `needs_llm` | 版面像标题但词典不认识，要交给模型归类 |

### resumes 的其他 JSON

- `layout_detail`：`[{page_no, layout_type, confidence, gap: [x0, x1] | null}]`，gap 是分栏的空白带。
- `ats_signals`：`{images, textboxes, drawings}`。目前只有 `images`（图片数）是真实统计的，`textboxes`、`drawings` 恒为 0（`parser/extract.py`）。

### diagnoses.score_detail

`{completeness, quantification, expression, consistency, ats}`，各 0–100；在当前 `mode` 下没有来源的维度为 null。

### findings.rewrite 与 match_reports.items[].advice

两处结构相同，都是点开时现场生成、存下来的具体建议：

```json
{ "text": "…", "violation_count": 0, "prompt_version": "advice-v1", "model": "deepseek-chat", "created_at": "2026-10-07T10:21:05" }
```

`violation_count` 是数字复检时，原文没有、被换成【数值】占位符的数字个数。

### jobs.requirements

```json
[ { "id": 1, "req_type": "hard", "category": "skill", "content": "熟悉 Redis", "skill": "Redis", "skill_id": 40,
    "weight": 1.0, "quote": "<raw_text[char_start:char_end]>", "char_start": 120, "char_end": 128 } ]
```

`req_type` 取 hard / plus / soft，`weight` 由它决定；`category` 取 skill / education / experience / other，`skill` 只有技能类才有；`quote` 是 JD 原文的逐字引用，定位不到原文的要求在解析时就丢掉了。

### match_reports.items

```json
[ { "requirement_id": 1, "content": "熟悉 Redis", "req_type": "hard", "category": "skill", "weight": 1.0, "skill": "Redis",
    "status": "hit", "matched_by": "fulltext", "reason": "…",
    "evidence_quote": "<full_text[char_start:char_end]>", "char_start": 560, "char_end": 590, "unit_id": "work[0]",
    "advice": null } ]
```

`status` 取 hit / partial / miss；`matched_by` 取 dict / profile / fulltext，没人判过的 miss 为 null；`advice` 只有没满足、部分满足的要求点开过才有。

### interview_sessions.plan

```json
{ "topics": [ { "idx": 0, "source": "project", "ref": "P1", "label": "二手交易平台 · 缓存", "intent": "…" } ],
  "materials": { "job_title": "", "company": null, "domain": "cs", "requirements": [], "experiences": [],
                 "findings": [], "context": null, "context_mode": "none" } }
```

`source` 取 project / requirement / finding，`ref` 指向材料里的编号（P1、R9、F128）。`materials` 是建面试时整理好的材料，存在这里，检查点丢了也能重建；这场面试的求职方向就是 `materials.domain`。`context_mode` 取 none（没贴面经）/ full（不超过 3000 字，整段放在 `context`）/ retrieval（更长，切段进 Chroma，`context` 为 null）。

### interview_sessions.report

```json
{ "overall": 71, "verdict": "pass", "threshold": 60.0, "mode": "normal",
  "topics": [ { "idx": 0, "label": "", "source": "project", "score": 73 } ],
  "strengths": [ { "title": "", "detail": "" } ], "weaknesses": [ { "title": "", "detail": "" } ],
  "links": [ { "kind": "requirement", "ref_id": 9, "topic_idx": 2, "label": "", "text": "" } ],
  "answered": 8, "early": false, "summary_ok": true, "prompt_version": "interview-v2", "created_at": "2026-10-07T11:45:59" }
```

- `verdict`：pass / fail / practice（练习模式不下结论）/ incomplete（没聊完所有话题就结束，不下结论）。`threshold` 是出报告时的及格线。
- `topics[].score` 是话题分，没问到的为 null；`overall` 是问到了的话题的平均分。
- `early`：没走完全部话题就出的报告为 true（用户点了提前结束、花费到了单场上限、或被收尾成 abandoned）；`summary_ok`：模型写的文字总结成功了没有，失败时 `strengths`、`weaknesses` 为空，`links` 用固定的一句话。
- `links` 只挑得分低于 60、来源是简历问题或岗位要求的话题。

### interview_turns.evaluation

```json
{ "skipped": false, "scores": { "correctness": 4, "depth": 2, "clarity": 4 }, "score": 67,
  "evidence": [ { "quote": "先更新数据库再删缓存", "char_start": 0, "char_end": 10, "verify_result": "exact" } ],
  "good": "", "bad": "", "better_answer": "", "number_violations": 0, "decision": "followup", "low_evidence": false }
```

- 三项各 0–5，`score` = 三项平均 × 20。跳过的题 `scores` 为 null、`score` 为 0，没有 `number_violations`。
- `evidence` 从**这一题的回答文本**里逐字引用，经 `locate_span` 校验（不变量⑥），区间相对回答文本。校验失败的引用丢弃；一条有效引用都没有时带着原因重试 1 次，仍然没有就三项都给中性 3 分、标 `low_evidence`，聚合话题分时权重减半。
- `number_violations`：`better_answer`（参考答法）里候选人没说过、被换成【数值】的数字个数。只存库，不对外返回：接口和 SSE 只给 `interview_service._PUBLIC_EVAL` 里的键。
- `decision`：followup（追问）/ next（换下一个话题）。

## 2.4 预留字段（本期不写）

下面这些列或取值建表时留着，代码目前不写或只写固定值：

| 字段 / 取值 | 现状 |
|---|---|
| `resumes.parent_id`、`version_no` | 简历版本链，恒为 NULL / 1 |
| `resumes.is_corrected`、`corrected_at` | 对应未实现的 `PATCH /resumes/{id}/structure`（人工纠正结构），恒为 0 / NULL；「纠正后 `overall_score` 置 NULL」也没做 |
| `resumes.file_type` 的 docx | 只收 PDF，恒为 pdf。DOCX 相关的约定（`page_count`、`bbox`、坐标为 NULL，`layout_type` 恒为 single）都不会出现 |
| `resumes.used_llm_fallback` | 恒为 0：版面不做大模型兜底（04-design 4.8），接口里的同名字段也先留着 |
| `resumes.ats_signals` 的 textboxes、drawings | 恒为 0 |
| `diagnoses.status` 的 cancelled | 没有取消功能 |
| `jobs.parse_status` 的 pending、failed | JD 同步解析，失败不保存，只会写 success |
| `match_reports.gap_summary` | 不写：未通过说明由 `GET /apply/{id}` 读取时组装 |
| `interview_sessions.current_round`、`interview_turns.round` 的 hr | 只做一轮专业面，恒为 tech |
| `structure.skill_mentions[].matched_by` | 恒为 dict |

## 2.5 Chroma

模拟面试是主流程里唯一往 Chroma 写数据的地方（06-workflows 6.5）；匹配不检索（06-workflows 6.5）。

```
interview_ctx  面经切段          用户贴的面经 / 公司介绍超过 3000 字时切段（约 500 字一段）入库，metadata {session_id, idx}；
                                 每个话题召回 → 精排取 3 段；会话结束即删（retrieval/context_store.py）
resume_units   简历经历切块      已删除：只在 06-workflows 6.5「逐条检索 vs 全文判定」对照实验里用过，主流程不用；
                                 代码见提交 ee10f38 里的 retrieval/unit_store.py、matching/units.py
cases          优秀描述案例      暂缓：改写本期不检索（06-workflows 6.5），有范例库后再建
```

## 2.6 初始数据与建库

- skills 表和岗位模板（`jobs.is_template = 1`，16 份：计算机 7、运营 5、财会金融 4；「其他」方向没有模板）在 `backend/sql/seed.sql` 里，由 `scripts/dump_seed.py` 生成：技能来自 `data/skills_seed.csv`，模板原文在 `data/job_templates/`，先由 `scripts/build_job_templates.py` 解析成 `data/job_templates.json`（导入时不调模型，每次导入的要求项都一样）。
- 本机：在 MySQL 里先执行 `schema.sql`，再执行 `seed.sql`。
- Docker：`docker-compose.yml` 把两个文件挂到 MySQL 镜像的 `/docker-entrypoint-initdb.d/`，数据卷为空（首次启动）时自动按顺序执行；数据卷里已有数据就不会再执行，改了表结构要自己迁移或清空数据卷。
- 后端启动时只检查表是否齐全，缺表直接报错退出，不会自动建表。
- `uploads/`、`chroma/`、`checkpoints.sqlite`、`.env` 进 `.gitignore`。

## 2.7 设计说明

| 决策 | 理由 |
|---|---|
| 投递不单独建表：`match_reports` 一行就是一次投递，`diagnosis_id` 指向同一次的诊断 | 投递就是「诊断 + 匹配 + 初筛」一次跑完，结论都在匹配报告里；多一张表只多一层关联 |
| 面试记录（话题、深度、turns）存 DB，是权威来源；图 B 另用 `SqliteSaver` 检查点续跑（06-workflows 6.3） | 报告、页面、评测都读 DB；检查点丢了由 turns 重建 |
| 计划、报告、评分存 JSON | 只整体读写，不按里面的键查询 |
| 面试评分的依据走同一个 `locate_span` | 诊断、匹配、面试评分共用一套防幻觉机制 |
| `jobs.is_template` | 没有具体 JD 的用户也能投递、面试 |
| 简历、岗位软删除；`match_reports.items` 冗余存要求内容 | 老的投递和面试报告还要引用它们，岗位删了报告照样读得懂 |
