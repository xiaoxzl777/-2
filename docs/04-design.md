> Exported from design plan v3 (2026-09-18). Source of truth: this docs/ folder; update docs before changing code.

# 四、AI 模块设计

## 4.1 AI 应用点

| # | 场景 | 时机 | 类型 | temp | 设计要点 |
|---|---|---|---|---|---|
| 1 | 版面重排兜底 | 解析期 | LLM | 0 | 输入带编号块（已掩码），**只输出块序号** |
| 2 | 章节归类兜底 | 解析期 | LLM | 0 | 词典未命中且特征分 ≥3 的疑似标题 |
| 3 | 结构化抽取 | 解析期 | LLM | 0 | 按章节送带编号块；条目输出 `block_ids`；**basics 不送** |
| 4 | **语义诊断** ★ | 诊断期 | LLM | 0 | 单条目送审，json_mode，evidence 必须为子串 |
| 5 | JD 解析 | 匹配期 | LLM | 0 | 拆要求项 |
| 6 | **技能匹配判定** ★ | 匹配期 | LLM | 0 | 词典未命中的要求项一次送审；逐项输出 status + 逐字引用的简历原文，经 locate_span 校验 |
| 7 | 技能语义召回 | 解析/匹配 | Embedding | — | 只对词典未命中的词条 |
| 8 | 改写建议 | 按需 | LLM + RAG | 0.3 | 占位符 + 确定性复检 |
| 9 | 差距分析 | 匹配期 | LLM | 0.3 | 输入为逐项匹配结果 |
| 10 | **面试计划** ★ | 面试创建 | LLM | 0.3 | 输入：structure、top-8 findings、requirements、gap、extra_context 片段 → topics[]，每个带来源 |
| 11 | **回答评估** ★ | 每轮 | LLM | 0 | rubric 结构化输出，evidence 逐字引用回答并经 locate_span 校验 |
| 12 | **下一问生成** ★ | 每轮 | LLM | 0.7 | 输入：persona、当前话题、历史摘要、上题评估 → decision + question（流式） |
| 13 | 面试报告 | 面试结束 | LLM | 0.3 | 分数由确定性聚合，LLM 只写 strengths/weaknesses/better_answer |

## 4.2 明确不用 AI 的地方

```
basics 抽取 / 规则诊断 / 证据校验 / 综合评分 / 时间归一化 / 分栏与表格 / 技能匹配判定 / 占位符复检
面试：轮次推进（tech→hr）、追问层数上限、题数预算、每轮与综合分数的聚合、通过判定 —— 全部确定性逻辑
```

## 4.3 解析流水线（图 A 的 parse 子图，见 [06-workflows](06-workflows.md) 6.2）

```
extract → (扫描件判定) → layout（PDF：页眉页脚/表格/region-first/阅读顺序/项目符号分块；DOCX：线性）
→ full_text 与偏移固定 → fallback（PDF unknown 页 → llm_relayout 只回序号 → 重排重算）
→ section → basics（本地）→ structure（LLM 回 block_ids → 服务端切片）→ normalize → mentions → persist（同一事务）
```

## 4.4 诊断工作流（图 A 的 diagnose 子图，见 06-workflows 6.2）

```
rule_scan（mode=llm_only → []）
  → dispatch_review（成本预检；mode=rule_only 或无 unit → merge；否则 Send × N）
    → review_unit × N（节点内：LLM json_mode → 解析失败重试 → 每条 finding locate_span → 失败带反馈重试 ≤2 → 通过/丢弃）
  → merge_findings（同 category 且区间重叠 ≥50% 去重，规则优先）
  → score（五维，null 维重归一）
图形状对三种 mode 相同；mode 只在两个节点内各一个 if。
```

```python
class DiagnoseState(TypedDict):
    diagnosis_id: int
    mode: Literal["rule_only", "llm_only", "hybrid"]
    job_title: str | None
    full_text: str                              # 已做长度不变的 PII 掩码
    structure: dict
    review_units: list[dict]
    units_skipped: int
    rule_findings: Annotated[list, add]
    llm_findings: Annotated[list, add]
    rejected_findings: Annotated[list, add]
    schema_errors: Annotated[int, add]
    cost: Annotated[float, add]
    cost_limit: float
```

落库（diagnose_service，图外）：一次 `SELECT parsed_blocks` 映射 page_no/bbox；写 findings（含 failed 行）；统计首轮数；`status` 与 `resumes.overall_score` 同事务。

## 4.5 语义诊断 Prompt 骨架

```
[System]
你是一位资深技术招聘官，审阅候选人简历中的单条经历描述。只评价文本表述质量，不评价候选人本人，不判断事实真伪。
审查维度：depth_mismatch / vague / exaggeration / unclear_ownership / incoherent
硬性约束：
  · evidence_quote 必须是【原文】的连续子串，逐字摘录，不得改写、概括、增删标点
  · 无法逐字定位的问题一律不报告
  · 每条经历最多 3 个问题，按严重程度降序
  · 不重复报告【规则引擎已检出】中的问题
  · 以 JSON 输出：{"findings":[{"risk_type":"vague","severity":"medium","evidence_quote":"...","reason":"...","suggestion":"..."}]}
[User]
【目标岗位】{job_title 或 "未指定"}  【条目类型】{unit_type}
【原文】{full_text[unit.char_start:unit.char_end]}
【规则引擎已检出】{rule_findings_summary 或 "无"}
```

重试反馈：`你上一次返回的 evidence_quote 无法在原文中定位："{failed_quote}"。请重新审查，evidence_quote 必须是原文的连续子串。`

## 4.6 RAG 设计

| 应用点 | 检索什么 | 结果给谁 | 完整 RAG |
|---|---|---|---|
| 改写 few-shot | `cases`：metadata 过滤（job_category）→ embedding 召回 top-20 → reranker 精排 top-3 | LLM | ✅ |
| 匹配判定 | `resume_units`（简历每条经历）：embedding 召回 top-10 → reranker 精排 top-3 | LLM 判定要求项是否命中 | ✅ |
| 面试出题 | `resume_units` + `interview_ctx`（JD 原文 / 公司介绍 / 面经切块）：各自 embedding 召回 top-10 → reranker 精排 top-3 | 面试计划 / 下一问 LLM | ✅ |

三处共用 `retrieval/retriever.py` 的同一条链路：**切块 → 向量化入库 → 召回（embedding）→ 精排（reranker，cross-encoder）→ 注入 prompt**。
为什么要两阶段：embedding 是双塔模型，query 与文档各自编码，快但粗；reranker 把 query 与每个候选拼在一起过模型，准但慢——所以先用前者把上千条缩到 20 条，再用后者挑 3 条。
reranker 失败或关闭时退化为直接取召回 top-3，功能不中断。

**"模拟某家公司"的信息来源**：LLM 不依赖对公司的先验记忆。必填 JD（用户粘贴）给出"这家公司要什么"；可选 `company_name` + `extra_context`（面经、公司/部门介绍）给出"这家公司怎么问"；没有 JD 时用内置岗位模板。面试官 persona 的 system prompt 显式写入这些材料。

## 4.7 隐私

```
basics         本地抽取，永不出现在任何 prompt
mask_pii       长度不变：手机号数字→'X'、邮箱字符→'*'；应用于所有外发的简历文本
interview_ctx  会话 completed/abandoned 时删除该 session 的切块
cases / jd     仅公开数据；build_case_store.py 不读 resumes 表
清理           软删除 30 天后物理删除；llm_calls 不存正文（评测批次除外，写文件）
```

## 4.8 成本、缓存、审计（llm/client.py 唯一出口）

```
client.invoke(scene, messages, schema?, ref, model?, stream?)：
  ① 渲染 prompt → key = llm:{scene}:{model}:{prompt_ver}:{sha256(rendered_prompt)}
  ② 缓存命中 → 记 llm_calls 一行（cache_hit=TRUE, token/cost=0）→ 返回      （面试 iv_ask / iv_eval 不走缓存：每次对话都不同）
  ③ Redis 令牌桶限流
  ④ 调模型；token 取自 AIMessage.usage_metadata；cost 按单价表；取 system_fingerprint
  ⑤ 写缓存（TTL 7d）+ llm_calls 落库 → Result{parsed, raw, cost, tokens}
client.embed / client.rerank 同样五步；降级：失败记 WARNING，不阻塞（rerank 失败退化为召回序）
评测模式：run_id 存在 ⇒ 跳过缓存，prompt/response 写 data/eval_runs/{run_id}/calls.jsonl
```

成本：单份诊断约 0.01–0.02 元；单场面试（约 14 题 × 2 次 + 计划 + 报告 ≈ 30 次）约 0.04–0.08 元。

## 4.9 模拟面试（图 B：LangGraph interrupt + SqliteSaver，见 06-workflows 6.3）

下面的推进规则仍然有效，只是由图 B 的 `decide` / `round_summary` 纯函数节点实现，状态游标在检查点里、问答记录在 MySQL。

```
创建  POST /interviews
  ① 校验：match_report 存在且 success；gate = passed 或 practice=true
  ② extra_context > 3000 字 → 切块 embed 进 interview_ctx
  ③ iv_plan：一次 LLM 调用 → topics[]（tech 默认 ≤8 题预算，hr ≤6）；每个 topic 检索 top-3 上下文片段存 plan
  ④ status=planned

开始  POST /interviews/{id}/start
  current_round=tech, topic=0, depth=0 → iv_ask（流式）→ 写 interview_turns（question）→ status=in_progress

作答  POST /interviews/{id}/answer {text}
  ① 状态校验（in_progress 且最后一题未答）；空答/"跳过" → 记 decision=next，不评估
  ② iv_eval：rubric 结构化输出（scores + evidence[] + feedback + better_answer + decision）
     evidence 每条经 locate_span(quote, answer_text) 校验，失败丢弃；全丢 → scores 置中性 3 分并标 low_evidence
  ③ 确定性推进：
       decision=followup 且 depth<2 且 topic 预算未耗尽 → depth+1，同 topic
       否则 → topic+1, depth=0；topic 超出本轮 → round_end（算本轮分）→ 切 hr；hr 也结束 → finished
       cost ≥ cost_limit → 立即 finished
  ④ 推送 evaluation 事件 → iv_ask 流式出下一问（或 round_end / finished）
  ⑤ 写 turns、更新 session 游标与 cost，同一事务；last_active_at 刷新

结束  finished → iv_report（LLM 只写 strengths/weaknesses/better_answer 汇总；分数由确定性聚合）
      → report JSON → status=completed → 删 interview_ctx 切块
放弃  启动清理：last_active_at < now-24h 且 in_progress → 按已答题聚合出报告 → abandoned
```

**结论更正（v4）**：此前决定不用 LangGraph 做面试，理由是 Redis 检查点依赖 Redis Stack。`SqliteSaver` 为本地文件、零部署，该理由不成立；`interrupt()` 正是为「停下来等人输入」设计的。现改为图 B，详见 06-workflows 6.3。

## 4.10 面试 Prompt 骨架

```
[System · 技术面]
你是 {company_name 或 "目标公司"} 的技术面试官，正在面试「{job_title}」岗位的候选人。
岗位要求：{requirements 摘要}    参考材料：{context_snippets 或 "无"}
候选人简历要点：{structure 摘要（无 basics）}    已发现的薄弱点：{findings 摘要}
风格：追问具体做法与验证方式，不接受泛泛而谈；一次只问一个问题；不透露评分。

[System · HR 面]
你是 {company_name 或 "目标公司"} 的 HR 面试官……
关注：经历真实性与职责边界（STAR）、求职动机与岗位匹配、沟通表达；不问技术细节。

[iv_eval · 技术面 rubric]  correctness / depth / clarity 各 0–5；evidence 必须逐字引用候选人回答
[iv_eval · HR 面 rubric]   star_completeness / motivation_fit / communication 各 0–5
输出 JSON：{"scores":{...},"evidence":[{"quote":"..."}],"feedback":"...","better_answer":"...","decision":"followup|next|end_round"}

[iv_ask]  输入：persona、当前 topic（intent/来源/上下文片段）、本轮历史（问答摘要）、上题评估、depth
          输出：一个问题（流式纯文本）；depth>0 时必须承接上一答中的具体点
```

---

# 五、核心算法

## 5.1 region-first 分栏（PDF）

```
1  页眉页脚剔除：y 在页顶/页底 6% 内 且（跨页同位置同文本 或 匹配页码正则）→ 删
2  表格区域：find_tables()；接受 行≥2 列≥2 且 ≥半数单元格有字；表内按行出块（" | " 连接），column_index=0，不参与投影
3  X 轴投影：候选空白带 = 宽度 ≥ 3%·W 且左右都有文字；c = 带内无文字高度 / 页面文字总高度，取 c 最大者
4  max c < 0.3 → single，confidence=1-c，按 y 排序，结束
5  跨栏行 = 压住 gap 的行，column_index=-1；用跨栏行把页面横切为 region
6  每个 region 重算投影：c ≥ 0.8 → double（c）；c ≤ 0.3 → single（1-c）；否则 unknown（0.5）
   sidebar = double 且 gap 中心 <40%·W 或 >60%·W（仅标签）；table = 表格字符占比 ≥ 70%
7  页级结果 = 最高 region 的 (type, confidence, gap)；无 region → single/1.0
8  阅读顺序：跨栏行与 region 按 y；region 内左→右；栏内按 y；遇项目符号（• - · ① 1.）另起块
简历级：layout_type 取第 1 页；confidence 取各页最小；layout_detail 逐页
常数：6% / 3% / 0.3 / 0.8 / 70%，写进 config
```

## 5.2 full_text 契约与 locate_span

```
full_text = "\n".join(b.text for b in blocks_by_index)；char_end 开区间；下一块 start = 上一块 end + 1
单位：Unicode 码点；extract 阶段非 BMP → U+FFFD ⇒ Python len == JS .length
冻结：偏移算出后不得再 strip / 折叠空白 / NFC / 全半角转换
匹配用归一化（长度不变）：全角标点→半角一对一，\n \t → 空格

locate_span(quote, text, hint=(lo,hi)) -> (start, end, score) | None
  text[lo:hi] 上：① str.find → 1.0  ② rapidfuzz partial_ratio_alignment ≥ 90 → 对齐区间
  都失败 → 全文再 ①②；返回全局偏移；None 即不可定位
用途：诊断 evidence（hint=条目区间）、structure 中 skills 细化（hint=块区间）、面试评分 evidence（text=回答）
```

## 5.3 DOCX 线性读取

按 body 子元素顺序：段落一块；表格逐单元格、单元格内逐段落（合并单元格去重，嵌套表不处理）；文本框 `.//w:txbxContent` 只计数进 ats_signals。

## 5.4 章节识别

8 类：`basics / summary / education / work / projects / skills / awards / other`。双语三步匹配：整行==别名 → 去拉丁后中文==中文别名 → 去中文后拉丁==英文别名。

| 特征 | 分值 |
|---|---|
| 词典命中 | +3 |
| 字号 ≥ 正文中位数 × 1.15 | +1 |
| 加粗 | +1 |
| 孤行且 ≤ 12 字 | +1 |
| 上方留白 ≥ 1.5 行高（PDF） | +1 |

分 ≥ 3 判标题；`confidence = min(1, 分/5)`；词典未命中的标题 → LLM 归类兜底。

## 5.5 时间归一化

```
先按「date 连接符 date」整体匹配（- – — ~ ～ 至 到 to），失败再单个 date
去空白后匹配；month 后 (?!\d) 且 1–12 校验
支持 2023.9 / 2023.09 / 2023/9 / 2023年9月 / Sep 2023 / 2023；至今/Present/现在 → end=null, is_present=true
两端精度不一致取粗；单个日期 end=null；失败整字段 null；输出 "YYYY-MM" 或 "YYYY"
```

## 5.6 技能提及抽取与「词典 + LLM」匹配

```
extract_mentions(full_text, sections, structure)：
  ① 词典路：skills 的 canonical+aliases 编一条正则（长度降序、忽略大小写、ASCII 加 \b）扫全文，按 sections 标 section_type
     纯本地、无 API；词典里没有的词不产生 mention（skill_id 留 null），不影响后续 LLM 判定

JD 要求项 ↔ 简历：
  ① 词典路（确定、免费）：要求项有 skill_id 且 skill_mentions 中存在同 skill_id → hit，matched_by='dict'，证据取 mention 区间
  ② RAG + LLM 路：其余要求项逐条 → resume_units 召回 top-10 → reranker 精排 top-3 → LLM 判定
     输出 {status: hit|partial|miss, unit_id, reason}；证据即该 unit 的 char 区间（unit_id 不在候选内 → 计入 hallucination_count 并按 miss）
     matched_by='rag'
  ③ 复核：② 判为 miss 的，用掩码后的简历全文让 LLM 复核一次，hit/partial 须给 evidence_quote 并经 locate_span 校验；matched_by='fulltext'
  mode：dict_only / llm_fulltext / llm_rag / hybrid，见 06-workflows 6.2
为什么不建本体树：上下位知识（Spring Boot 属于 Java 生态）LLM 本来就有，手工建树覆盖面永远不够；
  词典只保留「同一技能的不同写法」这种确定性最高、LLM 也无需判断的部分。与诊断模块同一原则：确定的先上，模糊的交给 LLM，LLM 输出必须可验证。
degree_level(structure)∈{0..4}；experience_years(structure) = work[] 区间合并求和
```

## 5.7 综合评分（诊断）

```
dim_score[d] = max(0, 100 − Σ penalty)，high 25 / medium 12 / low 5；无来源维度 null
初始权重 0.25 / 0.25 / 0.20 / 0.20 / 0.10（M8 评测后调整）；overall 只对非 null 维度加权归一
```

## 5.8 改写占位符复检

```
check_placeholders(original, rewritten)：正则提取 rewritten 中的 \d+(\.\d+)?\s*(%|倍|ms|万|k)?，original 中不存在的即违规
违规 → 带反馈重试 1 次；仍违规 → 替换为【数值】并追加 placeholder，violation_count 入 rewrite JSON
评测复检时占位符视作已量化
```

## 5.9 面试评分聚合（确定性）

```
每题分 = mean(rubric 三维) × 20（0–100）；low_evidence 的题权重 0.5
话题分 = 该 topic 各题分均值（追问题计入）
轮次分 = 话题分均值；technical 通过线 60
综合   = 0.6 × tech + 0.4 × hr；verdict = pass 若 tech ≥ 60 且综合 ≥ 60，否则 improve
weaknesses 候选 = 分数最低的 3 个话题 + 其 linked_finding；strengths = 最高 2 个
```

---

# 六、后端设计

## 6.1 分层与目录

```
api/        路由层 —— 薄
services/   业务层 —— 流程编排、事务、DB；面试状态机在 interview_service
parser/ diagnose/ matching/ interview/ graphs/   领域层 —— 纯逻辑

backend/app/
├── main.py（lifespan：redis.ping、启动清理、技能词典正则）  config.py  database.py  deps.py
├── models.py（11 张表）  schemas.py
├── api/        auth.py resume.py diagnose.py job.py match.py rewrite.py interview.py system.py
├── services/   resume_service.py diagnose_service.py match_service.py rewrite_service.py interview_service.py
├── parser/     extract.py layout.py ★ section.py structure.py normalize.py pii.py
├── diagnose/   rules.py evidence.py ★ scorer.py placeholders.py
├── matching/   skill_dict.py ★（extract_mentions） matcher.py ★ gap_analysis.py profile.py
├── interview/  planner.py（计划 prompt 组装与解析） rubric.py（评估 schema 与聚合） policy.py（推进规则）
├── retrieval/  chroma_client.py retriever.py ★（召回 + 精排） unit_store.py case_store.py ctx_store.py
├── graphs/     state.py apply_graph.py（图 A）parse_graph.py diagnose_graph.py match_graph.py interview_graph.py（图 B）nodes/ checkpoint.py
├── llm/        client.py ★ registry.py prompts.py
├── cache/      redis_client.py llm_cache.py ratelimit.py pubsub.py
└── tasks.py

scripts/   dump_schema.py dump_seed.py build_case_store.py gen_eval_set.py run_eval.py
data/      skills_seed.csv jd.jsonl cases.jsonl resumes/ uploads/ chroma/ eval_runs/
tests/     test_layout.py test_fulltext_contract.py test_evidence.py test_rules.py test_normalize.py test_interview_policy.py

frontend/src/
├── pages/       Upload  Analysis★  JobMatch（含初筛结果与"进入面试/练习模式"）  Rewrite  Interview★（流式聊天）  InterviewReport
├── components/  ResumeViewer★（文本视图，char 区间高亮） FindingPanel DiffView ChatStream ScoreCard charts
└── store/ api/ types/
```

## 6.2 Redis 职责与可用性约定

```
① LLM/embedding/rerank 缓存（面试逐轮调用不缓存）   ② 限流令牌桶   ③ 后台任务 SSE pub/sub
④ LangGraph checkpoint：不用 Redis；图 B 用 `SqliteSaver`（`data/checkpoints.sqlite`）
Redis 与 MySQL 同为必需依赖，启动 ping 失败即退出；运行期唯一容错：llm_cache get/set 异常按 miss。
```

## 6.3 启动清理（lifespan，单进程，只跑一次）

```sql
UPDATE resumes            SET parse_status='failed', parse_error='interrupted' WHERE parse_status='parsing';
UPDATE diagnoses          SET status='failed', error_msg='interrupted'          WHERE status='running';
UPDATE match_reports      SET status='failed', error_msg='interrupted'          WHERE status='running';
-- 面试：in_progress 且 last_active_at < now-24h → 按已答题聚合报告 → abandoned；删 interview_ctx 切块
-- 软删除 30 天：删文件 + DELETE resumes（CASCADE）
```

## 6.4 上传与存储 / 6.5 配置

同 v2：五步校验、UUID 落盘、不挂 StaticFiles、同用户去重；`pydantic-settings` 读 `.env`，仓库只提交 `.env.example`。
