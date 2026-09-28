> 最后更新：2026-09-27。改设计先改这里的文档再改代码；发现文档与代码不一致时以代码为准，回头改文档。

# 一、需求分析

## 1.1 角色

| 角色 | 说明 |
|---|---|
| 求职者 seeker | 唯一业务角色 |
| 管理员 admin | 查看系统用量 |

## 1.2 解析路径分流

```
文本版 PDF   → 完整版面流程：页眉页脚剔除 → 表格区域 → region-first 分栏 → 阅读顺序 → 章节 → 置信度 → LLM 兜底〔未实现〕
扫描件 PDF   → len(full_text.strip()) < 100 → parse_status='failed', parse_error='scanned_pdf' → 50003
DOCX         →〔未实现：本期只收 PDF，上传 .docx 直接 41501〕线性读取（段落与表格按文档流；表格逐单元格出块）；layout_type='single'、confidence=1.0、
               page_no=1、bbox=NULL、page_count=NULL；跳过分栏与 LLM 兜底
```

## 1.3 功能需求

### A. 账号与权限

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-A1 | 注册、登录，JWT（HS256，exp 24h，secret 读 .env） | P0 |
| FR-A2 | 所有资源按 `user_id` 隔离；越权访问视同不存在返回 404 | P0 |

### B. 简历管理

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-B1 | 上传校验清单 | 固定顺序，任一失败即拒收不落库：① 扩展名+魔数 → 41501 ② ≤20MB → 41301 ③ DOCX zip 解压总量 ≤100MB → 41501 ④ PDF `needs_pass` → 41501 ⑤ PDF `page_count>10` 或 DOCX 抽取后 >30,000 字 → 42201。〔DOCX 的两步未实现：本期只收 PDF〕 | P0 |
| FR-B2 | 列表与详情 | 分页，按 `updated_at` 排序 | P0 |
| FR-B3 | 版本链 | `parent_id` 字段保留，本期恒为 NULL；新版本走"重新上传 → 完整解析" | P2 |
| FR-B4 | 软删除 | 30 天后由启动清理物理删除 | P1 |
| FR-B5 | 文件去重 | `user_id=? AND file_hash=? AND is_deleted=0 AND parent_id IS NULL` 内判重，命中复用 | P2 |

### C. 解析（★ 核心）

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-C1 | 文本与坐标提取 | PDF：PyMuPDF 每块 bbox/字号/加粗；DOCX〔未实现〕：python-docx 段落顺序，`is_bold`=任一 run 加粗或样式名以 Heading 开头 | P0 |
| FR-C2 | **表格与分栏**（仅 PDF） | `page.find_tables()` 取有边框表（≥2 行 ≥2 列、≥4 格且 ≥ 半数格子有字），只用格子位置、文字仍用抽出的行；整张表缩成一块参与 region-first 分栏，排好位置后按行出块（5.1）。表格字数 ≥ 70% 的页判为 table。无边框的对齐"表格"不识别 | P0 |
| FR-C3 | 阅读顺序重建（仅 PDF） | 跨栏行与 region 按 y 排；region 内左栏→右栏，栏内按 y；遇项目符号另起一块 | P0 |
| FR-C4 | 章节识别 | 标题词典（中英/双语三步匹配）+ 特征加权（5.4），输出 8 类 + 置信度 | P0 |
| FR-C5 | LLM 兜底（仅 PDF） | 〔未实现，M8 前补，排在表格与章节兜底之后〕`layout_detail` 任一页 `unknown`（等价 `layout_confidence < 0.7`）→ 掩码文本+坐标交 LLM，**只回块序号**；在解析流水线内执行 | P1 |
| FR-C6 | 结构化抽取 | 按章节送 LLM，输入带编号的块；字段值输出文本，条目输出 `block_ids`，highlights **只输出 block_ids**，text 由服务端切片 | P0 |
| FR-C7 | 时间归一化 | 规则见 5.5；失败整字段为 null，规则遇 null 跳过 | P0 |
| FR-C8 | 人工纠正 | **只允许**改非文本字段值（degree/日期/kind/skill_id/level/条目归属章节/删除误抽条目）；不接收 text / char 区间 / full_text（400）。成功后 `is_corrected=TRUE`、`overall_score=NULL`、重算 `skill_mentions` | P1 |
| FR-C9 | 技能提及索引 | 解析末尾建 `skill_mentions`（5.6），全系统唯一"文本 → skill_id"入口 | P0 |
| FR-C10 | 解析调试视图 | 读 `layout_detail` 与 bbox 画分栏线、块框 | P2 |

### D. 诊断（★ 核心）

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-D1 | 规则引擎 | 7 类确定性规则，纯函数、不调 API，输入含 `skill_mentions` | P0 |
| FR-D2 | LLM 语义诊断 | 单条目送审；`json_mode` + `include_raw`；schema 失败与 evidence 失败共用重试路径 | P0 |
| FR-D3 | **证据溯源校验** | `locate_span(quote, text, hint)`：hint 内 精确 → RapidFuzz≥90 → 全局再来一遍；失败判 `evidence_mismatch` | P0 |
| FR-D4 | 校验-重试 | 失败带原因重试 ≤2 次，在 review_unit 节点内部完成 | P1 |
| FR-D5 | 风险分级 | high / medium / low | P0 |
| FR-D6 | 综合评分 | 按 `findings.category` 五维加权，无来源维度 null 并重归一；产品展示分 | P1 |
| FR-D7 | 成本预检 | 分发前一次预估，超限截断并置 `status='partial'` | P1 |
| FR-D8 | 异步 + SSE | `task_id="diagnose:{id}"`；轮询兜底读 DB status | P1 |

### E. JD 匹配与初筛（★ 核心）

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-E1 | JD 录入 | 粘贴原文 → LLM 拆 硬性/加分/软性 要求项，技能类回填 `skill_id`；可选公司名 | P0 |
| FR-E2 | 内置岗位模板 | 无具体 JD 时可选的通用岗位（后端/前端/算法/测试…，手写 5–8 份公开 JD 风格的模板），以 `jobs.is_template=1` 存 | P1 |
| FR-E3 | 规则 + LLM 匹配 | ① 规则先判（同义词词典命中且经历里用过、学历、年限；确定、免费）→ ② 规则判不了的要求连同简历全文一次交给 LLM，逐条判定 hit/partial/miss 并逐字引用简历依据，经 `locate_span` 定位，定位失败按 miss；`mode ∈ {dict_only, llm_fulltext, hybrid}` 供消融。匹配不用 RAG（简历与 JD 很短，见 06-workflows 6.2） | P0 |
| FR-E4 | 逐项匹配 | 命中/部分/缺失，证据取自 `skill_mentions` | P0 |
| FR-E5 | 匹配度评分 | 技能/经验/学历/项目四维 + 总分；学历与年限由 `degree_level()` / `experience_years()` 从 structure 算 | P0 |
| FR-E6 | 差距分析 | 缺失项 + 补齐建议：`POST /match/{id}/items/{requirement_id}/advice`，点开时现场生成、流式返回，存进 `match_reports.items[k].advice` | P1 |
| FR-E8 | **一键投递** | `POST /apply {resume_id, job_id}`：后台跑图 A（需要时解析 → 诊断与匹配并行 → 初筛），SSE 推进度；诊断由此自动触发并带上岗位名 | P0 |
| FR-E9 | 未通过说明 | 「哪里不符合」= 匹配差距 + 诊断 findings 合并排序；每条可跳原文高亮与改写 | P0 |
| FR-E7 | **初筛门槛** | `overall_match ≥ SCREEN_THRESHOLD`（默认 60）为"通过"；未通过展示差距与改写入口，**允许以练习模式进入面试** | P0 |

### F. 改写

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-F1 | 改写建议 | `POST /findings/{id}/advice`：点开时现场生成、流式返回，写回 `findings.rewrite`；针对原句给出【问题】【改成】【为什么】，**数值强制占位符 + 确定性复检**（5.8） | P1 |
| FR-F2 | 检索增强改写 | **暂缓**（06-workflows 6.5）：本期没有范例库，改写只做「模型改写 + 数字占位符复检」。以后有了 `cases` 再加 `?use_rag=true`（召回 top-20 → 精排 top-3 作 few-shot） | P2 |
| FR-F3 | 采纳改写 | 本期不写回简历：用户填占位符 → 前端合成 → 复制/下载 | P2 |
| FR-F4 | 报告导出 | PDF | P2 |

### I. 模拟面试（★ 应用层亮点）

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-I1 | 创建会话 | 输入 `apply_id`（必：从哪次投递的初筛结果进来）、`company_name`（选）、`extra_context`（选：面经/公司介绍，≤20,000 字）；投递须已分析完成 | P0 |
| FR-I2 | 初筛结果 | 返回 `gate:{passed, overall_match, threshold}`；未通过时 `mode='practice'`，通过的也可主动选练习模式 | P0 |
| FR-I3 | 面试计划 | 一次 LLM 调用定 5 个话题 `plan.topics[]`：每个带 `source`（project / requirement / finding）、`ref`（材料编号，代码核对）、`label`、`intent`；话题问到了才显示给用户 | P0 |
| FR-I4 | 逐题对话 | 图 B：出题前只检索面经（`extra_context` 超 3,000 字才切段检索 top-3，不长就整段给，没贴就跳过；简历和 JD 不检索）→ 流式出题 → `interrupt()` 等回答 → 评估（rubric + 逐字引用回答）→ 纯函数决策（每个话题最多追问 1 次 / 下一话题 / 出报告）；练习模式每题答完马上给点评，正常模式结束后看报告 | P0 |
| FR-I5 | 只做技术面 | 不做 HR 面（2026-09-27 定：太主观）；话题数、追问次数可配（默认 5 / 1） | P0 |
| FR-I6 | 面试报告 | `verdict ∈ {pass, fail, practice, incomplete}` 决定开头话术（通过 / 没过 / 练习模式不下结论 / 没聊完不下结论），几种情况的总结**同样完整**：每个话题的分、逐题回顾（问题 / 回答 / 评分 / 依据 / 参考答法）、与简历问题 / 岗位差距的关联（可跳回结果页对应的一条） | P0 |
| FR-I7 | 中断续答 | LangGraph 检查点（`SqliteSaver`，thread_id=`interview:{id}`）续跑；MySQL 为权威记录，检查点丢失时由 turns 重建；24h 无活动 → `abandoned` 并按已答题出报告 | P1 |
| FR-I8 | 异常处理 | 空答不能提交；"跳过" → 记 0 分、换下一个话题；跑题由评分反映；单场成本上限，到了就出报告；用户可提前结束 | P1 |
| FR-I9 | 语音 | 本期不做 | 未来工作 |

### H. 系统支撑

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-H1 | LLM / embedding / reranker 可插拔（注册表） | P0 |
| FR-H2 | Prompt 版本化常量，落库 `prompt_version` | P0 |
| FR-H3 | 调用审计：`llm/client.py` 唯一出口落库，缓存命中也记一行 | P1 |
| FR-H4 | 评测 CLI：`gen_eval_set.py` / `run_eval.py`（绕过缓存、`--repeat 3`） | P1 |
| FR-H5 | 数据种子：`scripts/dump_seed.py` 由 `data/skills_seed.csv`（技能词典）和 `data/job_templates.json`（岗位模板，由 `scripts/build_job_templates.py` 解析 `data/job_templates/*.txt` 生成）生成 `backend/sql/seed.sql`（可重复执行；模板按标题更新） | P1 |

## 1.4 非功能需求

| 编号 | 指标 |
|---|---|
| NFR-1 性能 | 单份解析 < 3s（不含 LLM）；完整诊断 < 30s；面试每轮首字 < 3s、整轮 < 15s |
| NFR-2 准确性 | 版面合成集（N=80，4 种版面，仅 PDF）line 级相邻行对顺序准确率 ≥ 95%；残留幻觉率（人工复核）≤ 2% |
| NFR-3 可靠性 | LLM 调用指数退避重试 3 次；启动时清理中断任务；面试会话可续答 |
| NFR-4 成本 | 单份诊断 `DIAGNOSE_COST_LIMIT`；单场面试 `INTERVIEW_COST_LIMIT`（默认 0.3 元），超限提前结束并出报告 |
| NFR-5 安全与隐私 | JWT；上传校验清单；UUID 落盘；按用户隔离；**PII 不进 LLM prompt**；案例库与 JD 语料仅公开数据；软删除 30 天清理；面试回答只用于本会话 |
| NFR-6 可复现 | `temperature=0` 仅降低随机性；可复现靠 固定 prompt_version + 记录 `model_version` 与运行日期 + 每组重复 3 次报均值±标准差 + 评测绕过缓存 |
| NFR-7 可维护 | 规则插件化；prompt 与代码分离；领域层零 DB 依赖 |

## 1.5 诊断规则清单（确定性通道，纯函数）

| 规则码 | category | 判定逻辑 |
|---|---|---|
| `STAR_INCOMPLETE` | completeness | highlight 无结果性表述 |
| `NO_QUANTIFICATION` | quantification | highlight 无 数字/百分比/倍数 |
| `WEAK_VERB` | expression | highlight 首动词命中弱动词表 |
| `SKILL_PROJECT_MISMATCH` | consistency | `skills[]` 中 skill_id 非 null，且 `skill_mentions` 里没有 `section_type∈{work,projects}` 且 skill_id 相同或为其子技能的记录 |
| `TIMELINE_ANOMALY` | consistency | 仅 `kind∈{work,internship}`：区间重叠或空窗 > 3 个月；null 或仅年份跳过 |
| `ATS_UNFRIENDLY` | ats | `ats_signals` 任一 > 0 |
| `LENGTH_ANOMALY` | expression | 单条 highlight > 120 字或 < 8 字；`page_count > 2`（NULL 时只查字数） |

LLM 通道 `risk_type`：`depth_mismatch` / `vague` / `exaggeration` → expression；`unclear_ownership` / `incoherent` → consistency。
