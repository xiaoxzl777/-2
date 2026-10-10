# 一、需求分析

本章只写「做什么、做到没有」：标〔未实现〕的是列了需求但还没做的。算法、阈值见 04-design，产品流程见 06-workflows。

## 1.1 角色

| 角色 | 说明 |
|---|---|
| 求职者 seeker | 唯一业务角色 |
| 管理员 admin | 查看系统用量〔未实现：`GET /system/info` 没做，`users.role` 只存不用〕 |

## 1.2 解析路径分流

```
文本版 PDF   → 完整版面流程：页眉页脚剔除 → 表格区域 → region-first 分栏 → 阅读顺序（含时间轴日期列）→ 章节 → 置信度（只作记录）
扫描件 PDF   → 抽出的字符 < 100（SCANNED_PDF_MIN_CHARS）→ parse_status='failed', parse_error='scanned_pdf' → 50003
DOCX         → 只收 PDF，上传 .docx 直接 41501
```

## 1.3 功能需求

### A. 账号与权限

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-A1 | 注册、登录，JWT（HS256，exp 24h，secret 读 .env）；登录后可修改密码（先输对当前密码），导航右上角头像菜单里进 | P0 |
| FR-A2 | 所有资源按 `user_id` 隔离；越权访问视同不存在返回 404 | P0 |

### B. 简历管理

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-B1 | 上传校验清单 | 固定顺序，任一失败即拒收不落库：① 扩展名+魔数（只收 PDF）→ 41501 ② ≤20MB → 41301 ③ 加密（`needs_pass`）→ 41501 ④ `page_count>10` → 42201 | P0 |
| FR-B2 | 列表与详情 | 分页，按 `updated_at` 排序 | P0 |
| FR-B3 | 版本链〔未实现〕 | 只留了 `parent_id` 字段，恒为 NULL；改了简历就重新上传、完整解析 | P2 |
| FR-B4 | 软删除 | 标 `is_deleted` / `deleted_at`；30 天后物理删除〔未实现〕 | P1 |
| FR-B5 | 文件去重 | `user_id=? AND file_hash=? AND is_deleted=0 AND parent_id IS NULL` 内判重，命中复用 | P2 |

### C. 解析（★ 核心）

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-C1 | 文本与坐标提取 | PyMuPDF 按行抽取 bbox / 字号 / 加粗 | P0 |
| FR-C2 | **表格与分栏** | 识别有边框的表格（只用格子位置，文字仍取抽出的行），整张表作为一块参与 region-first 分栏；无边框的对齐「表格」不识别（04-design 4.8） | P0 |
| FR-C3 | 阅读顺序重建 | 按分栏结果重建阅读顺序；时间轴版式的日期列用规则归位，版面不做 LLM 兜底（04-design 4.8） | P0 |
| FR-C4 | 章节识别 | 标题词典 + 特征加权，输出 8 类 + 置信度；词典认不出的候选标题一次交 LLM 归类（可判「不是标题」），失败时按没调模型处理；全文没有教育标题时，从开头段补出教育章节（04-design 4.10） | P0 |
| FR-C5 | 结构化抽取 | 按章节送 LLM，输入带编号的块；条目和 highlights 只回 `block_ids`，文字由服务端从原文切片；技能名须能在所属块里定位（04-design 4.9） | P0 |
| FR-C6 | 时间归一化 | 本地规则归一化；失败整字段为 null，下游规则遇 null 跳过（04-design 4.11） | P0 |
| FR-C7 | 人工纠正〔未实现：`PATCH /resumes/{id}/structure`〕 | **只允许**改非文本字段值（degree/日期/kind/skill_id/level/条目归属章节/删除误抽条目）；不接收 text / char 区间 / full_text（400）。成功后 `is_corrected=TRUE`、`overall_score=NULL`、重算 `skill_mentions` | P1 |
| FR-C8 | 技能提及索引 | 解析末尾建 `skill_mentions`，全系统唯一「文本 → skill_id」入口（04-design 4.12） | P0 |
| FR-C9 | 解析调试视图〔未实现〕 | 读 `layout_detail` 与 bbox 画分栏线、块框 | P2 |

### D. 诊断（★ 核心）

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-D1 | 规则引擎 | 7 类确定性规则（1.5），纯函数、不调 API，输入含 `skill_mentions` | P0 |
| FR-D2 | LLM 语义诊断 | 按单元送审（经历里的每条描述一个单元，另加个人总结）；`json_mode`；schema 失败与证据定位失败共用重试路径 | P0 |
| FR-D3 | **证据溯源校验** | 每条 finding 的引用经 `locate_span` 在本单元范围内定位回原文（04-design 4.9）；定位不到的标 `verify_result='failed'`，不展示 | P0 |
| FR-D4 | 校验-重试 | 失败带原因重试 ≤2 次，在 review_unit 节点内部完成 | P1 |
| FR-D5 | 风险分级 | high / medium / low | P0 |
| FR-D6 | 综合评分 | 按 `findings.category` 五维加权，无来源维度 null 并重归一（04-design 4.13）；产品展示分 | P1 |
| FR-D7 | 成本预检 | 分发前一次预估，超限截断并置 `status='partial'` | P1 |
| FR-D8 | 异步 + SSE | 诊断不单独触发，随投递在后台跑（`task_id="apply:{id}"`）；SSE 推进度，轮询兜底读 `GET /apply/{id}` | P1 |

### E. 岗位、投递与初筛（★ 核心）

按工作台的顺序：选方向 → 定岗位 → 投递 → 匹配与初筛 → 结果页 → 我的投递、我的简历。

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-E1 | 求职方向 | 工作台第一步选方向（计算机 / 运营 / 财会金融；还没有专门方向的选「其他」，按通用标准分析，选方向时、结果页、诊断报告里都提示「结果可能不够准，仅供参考」），存在岗位上（`jobs.domain`）；JD 解析、诊断、匹配、具体建议、面试都按岗位的方向取提示词与规则（领域包，04-design 4.16）；简历解析不分方向 | P1 |
| FR-E2 | JD 录入 | 粘贴原文（可填公司名）→ LLM 拆成 必须 / 加分 / 软素质 要求项；每条带 JD 原话，经 `locate_span` 定位，定位不到的丢弃；技能类回填 `skill_id` | P0 |
| FR-E3 | 内置岗位模板 | 没有具体 JD 时选通用岗位：手写 16 份实习岗模板（计算机 7、运营 5、财会金融 4；「其他」没有模板），按方向列出，以 `jobs.is_template=1` 存 | P1 |
| FR-E4 | **一键投递** | `POST /apply {resume_id, job_id}`：后台跑图 A（简历还没解析完就先等 → 诊断与匹配并行 → 初筛），SSE 推进度；诊断由此自动触发并带上岗位名 | P0 |
| FR-E5 | 规则 + LLM 匹配 | ① 规则先判（同义词词典命中且经历里用过、学历、年限；确定、免费）→ ② 规则判不了的要求连同简历全文一次交 LLM，逐条判 hit / partial / miss 并逐字引用简历依据，经 `locate_span` 定位，定位不到按 miss；`mode ∈ {dict_only, llm_fulltext, hybrid}` 供消融。匹配不用 RAG（理由见 06-workflows 6.5） | P0 |
| FR-E6 | 逐项匹配 | 命中 / 部分 / 缺失，每条带简历原文依据（词典命中取 `skill_mentions` 区间，模型判定取经 `locate_span` 定位的引用） | P0 |
| FR-E7 | 匹配度评分 | 按要求项类别分四维：技能 / 学历 / 经验 / 其他（skill / education / experience / other），JD 里没有该类要求的维度为 null；总分按权重加权。学历与年限由 `degree_level()` / `experience_years()` 从 structure 算 | P0 |
| FR-E8 | **初筛门槛** | `overall_match ≥ SCREEN_THRESHOLD`（默认 60）为通过；未通过展示差距与具体建议入口，**允许以练习模式进入面试** | P0 |
| FR-E9 | 未通过说明 | 「哪里不符合」是两个独立列表：对照岗位的差距 `gaps`（没满足与部分满足的要求，权重高的在前，同权重时 miss 在前）和简历自身的问题 `resume_issues`（诊断里定位成功的 finding，取最严重的 8 条）。由 `GET /apply/{id}` 读取时组装，每条可跳原文高亮、点开要具体建议 | P0 |
| FR-E10 | 差距建议 | 点开一条差距时现场生成【考察什么】【怎么补】【面试怎么答】：`POST /match/{id}/items/{requirement_id}/advice`，流式返回，存进 `match_reports.items[k].advice`，再打开直接显示 | P1 |
| FR-E11 | 我的投递 | `/app/applies`（`GET /apply`，分页）：每条投递的岗位、简历、结论，失败的给一句人话原因；这次投递下的面试挂在卡片上（进行中的可接着面，结束的看报告）；默认显示最近 10 条，更早的展开再看。结果页的成绩单里也显示这次投递面过的场次 | P1 |
| FR-E12 | 我的简历 | `/app/resumes`（只用现有接口：`GET /resumes` 带投递次数 + `GET /apply` 按简历分组）：上传（点选或拖进来）；每份的解析状态（失败的写原因）、最近投的 3 个岗位和分数；「看原文」看系统读出来的纸面（不画标注），「用它投递」回工作台并选好这份，「删除」原地确认 | P1 |

### F. 具体建议（改写）

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-F1 | 简历问题的建议 | 点开一条问题时现场生成【问题】【改成】【为什么】：`POST /findings/{id}/advice`，流式返回，写回 `findings.rewrite`；原文没有的数字一律换成【数值】占位（确定性复检，04-design 4.14） | P1 |
| FR-F2 | 采纳建议 | 【改成】那一行生成完可一键复制，【】里的占位由用户按实际填写；不写回简历 | P2 |
| FR-F3 | 诊断报告导出 | 结果页「预览报告」→ `/app/apply/:id/report`：初筛结论与分数、带编号标注的简历原文、岗位差距与简历问题（网页上生成过的具体建议一并放入，没生成的放规则的通用建议），排成 A4；「下载 PDF」在浏览器里直接生成文件，后端不参与 | P2 |

### G. 模拟面试（★ 应用层亮点）

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-G1 | 创建会话 | 输入 `apply_id`（必填：从哪次投递的初筛结果进来）、`company_name`（选填）、`extra_context`（选填：面经 / 公司介绍，≤20,000 字）；投递须已分析完成 | P0 |
| FR-G2 | 初筛结果 | 返回 `gate:{passed, overall_match, threshold}`；未通过时 `mode='practice'`，通过的也可主动选练习模式 | P0 |
| FR-G3 | 面试计划 | 一次 LLM 调用定 N 个话题（默认 5）：每个带 `source`（project / requirement / finding）、`ref`（材料编号，代码核对，指向不存在的丢掉）、`label`、`intent`；能用的不够 N 个就带原因重试一次，取能用话题多的那次；话题问到了才显示给用户 | P0 |
| FR-G4 | 逐题对话 | 图 B 逐题推进：流式出题 → 等回答 → 按 rubric 评分（依据逐字引用回答）→ 纯函数决定追问 / 换话题 / 出报告；只检索用户贴的长面经，简历和 JD 不检索（06-workflows 6.3、6.5）；练习模式每题答完马上给点评，正常模式结束后看报告 | P0 |
| FR-G5 | 面试轮次 | 只做一轮专业面（计算机方向叫技术面、运营方向叫运营面、财会金融和「其他」叫专业面），不做 HR 面；话题数、每个话题的追问次数可配（默认 5 / 1） | P0 |
| FR-G6 | 面试报告 | `verdict ∈ {pass, fail, practice, incomplete}` 决定开头话术（通过 / 没过 / 练习模式不下结论 / 没聊完不下结论），几种情况的总结**同样完整**：每个话题的分、逐题回顾（问题 / 回答 / 评分 / 依据 / 参考答法）、与简历问题 / 岗位差距的关联（可跳回结果页对应的一条） | P0 |
| FR-G7 | 中断续答 | LangGraph 检查点（`SqliteSaver`，thread_id=`interview:{id}`）续跑；MySQL 为权威记录，检查点丢失时由问答记录重建；很久没动静（默认 24 小时）的会话按已答的题出报告、标 `abandoned`，启动时收尾一次、之后每小时一次 | P1 |
| FR-G8 | 异常处理 | 空答不能提交；跳过记 0 分、换下一个话题；跑题由评分反映；单场成本到上限就出报告；用户可提前结束 | P1 |

### H. 系统支撑

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-H1 | 对话模型可插拔：`llm/registry.py` 的注册表（目前只登记了 deepseek-chat）；向量 / 重排只是 config 里的模型名（`EMBEDDING_MODEL` / `RERANKER_MODEL`） | P0 |
| FR-H2 | Prompt 版本化常量，落库 `prompt_version` | P0 |
| FR-H3 | 调用审计：对话（`llm/client.py`）与向量 / 重排（`llm/embedding.py`）每次调用落库 `llm_calls`，缓存命中也记一行 | P1 |
| FR-H4 | 评测 CLI：`gen_eval_set.py`（`--domain cs / ops / finance` 生成计算机 / 运营 / 财会评测集）；`run_eval.py`（`--task diagnose / match / interview`，`--set` 选评测集或题库，`--domain` 选领域包，`--repeat N`，绕过缓存）；面试评分题库 `interview_answers.py`（计算机）/ `interview_answers_ops.py`（运营） | P1 |
| FR-H5 | 数据种子：`scripts/dump_seed.py` 由 `data/skills_seed.csv`（技能词典）和 `data/job_templates.json`（岗位模板）生成 `backend/sql/seed.sql`（可重复执行；模板按标题更新）。`job_templates.json` 由 `scripts/build_job_templates.py` 解析 `data/job_templates/<方向>/*.txt`（`cs/`、`ops/`、`finance/`）生成 | P1 |

## 1.4 非功能需求

| 编号 | 指标 |
|---|---|
| NFR-1 性能 | 单份解析 < 3s（不含 LLM）；完整诊断 < 30s；面试每轮首字 < 3s、整轮 < 15s |
| NFR-2 准确性 | 版面合成集（120 份，6 种版式，仅 PDF）line 级相邻行对顺序准确率 ≥ 95%；模型引用的拦截率与定位准确率在降质集上自动统计（不做人工复核）。结果见 05-evaluation-and-plan 5.2–5.3 |
| NFR-3 可靠性 | LLM 调用指数退避重试 3 次；模型服务调不通（余额不足、密钥无效、连不上）时登录后页面顶上提示，出错处单独说明是「模型服务暂时不可用，请稍后再试」，不再和别的失败一样说「调用大模型失败」（04-design 4.6）；启动时把中断的解析 / 诊断 / 匹配标为失败；面试会话可续答，很久没动静的启动时和之后每小时收尾一次（04-design 4.18） |
| NFR-4 成本 | 单份诊断 `DIAGNOSE_COST_LIMIT`；单场面试 `INTERVIEW_COST_LIMIT`（默认 0.3 元），超限提前结束并出报告 |
| NFR-5 安全与隐私 | JWT；上传校验清单；UUID 落盘；按用户隔离；**PII 不进 LLM prompt**（04-design 4.5）；岗位模板为手写、不含公司名；软删除（30 天物理删除〔未实现〕）；面试回答只用于本会话 |
| NFR-6 可复现 | `temperature=0` 仅降低随机性；可复现靠 固定 prompt_version + 记录 `model_version` 与运行日期 + 每组重复 3 次报均值±标准差 + 评测绕过缓存（05-evaluation-and-plan 5.5） |
| NFR-7 可维护 | 规则插件化；prompt 与代码分离；领域层零 DB 依赖；加一个求职方向只需登记领域包、补词条和模板，流程代码不改 |

## 1.5 诊断规则清单（确定性通道，纯函数）

四个求职方向（含「其他」）用同一套规则（领域包可以按方向关掉个别规则，目前都没关）。

| 规则码 | category | 判定逻辑 |
|---|---|---|
| `STAR_INCOMPLETE` | completeness | 经历描述既没有结果词（提升 / 降低 / 上线…）也没有数字 |
| `NO_QUANTIFICATION` | quantification | 经历描述提到了结果词，却没有任何数字（Vue3、CET-6 这类名称里的数字不算） |
| `WEAK_VERB` | expression | highlight 首动词命中弱动词表 |
| `SKILL_PROJECT_MISMATCH` | consistency | 技能栏的技能在工作 / 项目经历里从没出现：词典认识的按 skill_id 比（`skill_mentions` 中 `section_type∈{work,projects}`），不认识的按字面查找；最多报 5 条 |
| `TIMELINE_ANOMALY` | consistency | 仅 `kind∈{work,internship}`：区间重叠或空窗 > 3 个月；null 或仅年份跳过 |
| `ATS_UNFRIENDLY` | ats | `ats_signals` 任一 > 0 |
| `LENGTH_ANOMALY` | expression | 单条 highlight > 120 字或 < 8 字；`page_count > 2`（NULL 时只查字数） |

LLM 通道 `risk_type`：`depth_mismatch` / `vague` / `exaggeration` → expression；`unclear_ownership` / `incoherent` → consistency。

---

不做的功能与未来工作见 05-evaluation-and-plan 5.8。
