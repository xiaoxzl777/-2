> Exported from design plan v3 (2026-09-18). Source of truth: this docs/ folder; update docs before changing code.

# 一、需求分析

## 1.1 角色

| 角色 | 说明 |
|---|---|
| 求职者 seeker | 唯一业务角色 |
| 管理员 admin | 查看系统用量 |

## 1.2 解析路径分流

```
文本版 PDF   → 完整版面流程：页眉页脚剔除 → 表格区域 → region-first 分栏 → 阅读顺序 → 章节 → 置信度 → LLM 兜底
扫描件 PDF   → len(full_text.strip()) < 100 → parse_status='failed', parse_error='scanned_pdf' → 50003
DOCX         → 线性读取（段落与表格按文档流；表格逐单元格出块）；layout_type='single'、confidence=1.0、
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
| FR-B1 | 上传校验清单 | 固定顺序，任一失败即拒收不落库：① 扩展名+魔数 → 41501 ② ≤20MB → 41301 ③ DOCX zip 解压总量 ≤100MB → 41501 ④ PDF `needs_pass` → 41501 ⑤ PDF `page_count>10` 或 DOCX 抽取后 >30,000 字 → 42201 | P0 |
| FR-B2 | 列表与详情 | 分页，按 `updated_at` 排序 | P0 |
| FR-B3 | 版本链 | `parent_id` 字段保留，本期恒为 NULL；新版本走"重新上传 → 完整解析" | P2 |
| FR-B4 | 软删除 | 30 天后由启动清理物理删除 | P1 |
| FR-B5 | 文件去重 | `user_id=? AND file_hash=? AND is_deleted=0 AND parent_id IS NULL` 内判重，命中复用 | P2 |

### C. 解析（★ 核心）

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-C1 | 文本与坐标提取 | PDF：PyMuPDF 每块 bbox/字号/加粗；DOCX：python-docx 段落顺序，`is_bold`=任一 run 加粗或样式名以 Heading 开头 | P0 |
| FR-C2 | **表格与分栏**（仅 PDF） | 先 `page.find_tables()` 取有边框表（≥2行≥2列、≥半数单元格有字）按行出块；剩余文字走 region-first 分栏（5.1） | P0 |
| FR-C3 | 阅读顺序重建（仅 PDF） | 跨栏行与 region 按 y 排；region 内左栏→右栏，栏内按 y；遇项目符号另起一块 | P0 |
| FR-C4 | 章节识别 | 标题词典（中英/双语三步匹配）+ 特征加权（5.4），输出 8 类 + 置信度 | P0 |
| FR-C5 | LLM 兜底（仅 PDF） | `layout_detail` 任一页 `unknown`（等价 `layout_confidence < 0.7`）→ 掩码文本+坐标交 LLM，**只回块序号**；在解析流水线内执行 | P1 |
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
| FR-E2 | 内置岗位模板 | 无具体 JD 时从 `jd_corpus` 统计生成的通用岗位（后端/前端/算法/测试…），以 `jobs.is_template=1` 存 | P1 |
| FR-E3 | 三路对齐 | ① alias 精确 → ② ontology 祖先链 → ③ embedding≥阈值（→ ④ rerank 可选）；前一路命中即停 | P0 |
| FR-E4 | 逐项匹配 | 命中/部分/缺失，证据取自 `skill_mentions` | P0 |
| FR-E5 | 匹配度评分 | 技能/经验/学历/项目四维 + 总分；学历与年限由 `degree_level()` / `experience_years()` 从 structure 算 | P0 |
| FR-E6 | 差距分析 | 缺失项 + 补齐建议 + 岗位技能分布（`jd_corpus`） | P1 |
| FR-E7 | **初筛门槛** | `overall_match ≥ SCREEN_THRESHOLD`（默认 60）为"通过"；未通过展示差距与改写入口，**允许以练习模式进入面试** | P0 |

### F. 改写

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-F1 | 改写建议 | `POST /findings/{id}/rewrite`，单条同步，写回 `findings.rewrite`；**数值强制占位符 + 确定性复检**（5.8） | P1 |
| FR-F2 | 检索增强改写 | `?use_rag=true` 检索 `cases` 作 few-shot | P1 |
| FR-F3 | 采纳改写 | 本期不写回简历：用户填占位符 → 前端合成 → 复制/下载 | P2 |
| FR-F4 | 报告导出 | PDF | P2 |

### I. 模拟面试（★ 应用层亮点）

| 编号 | 需求 | 说明 | 优先级 |
|---|---|---|---|
| FR-I1 | 创建会话 | 输入 `resume_id`、`job_id`（必）、`company_name`（选）、`extra_context`（选：面经/公司介绍，≤20,000 字）；须已有该 简历-JD 的匹配报告 | P0 |
| FR-I2 | 初筛结果 | 返回 `gate:{passed, overall_match, threshold}`；未通过时 `mode='practice'` | P0 |
| FR-I3 | 面试计划 | 一次 LLM 调用生成 `plan.topics[]`：每个话题带 `round`、`intent`、`linked_type/linked_id`（来源：finding / requirement / project）、`budget`（题数）；`extra_context` 超 3,000 字时切块向量化，按话题检索 top-3 片段注入 | P0 |
| FR-I4 | 逐题对话 | 用户作答 → 评估（rubric + 逐字引用回答）→ 决策（追问 ≤2 层 / 下一话题 / 结束本轮）→ 下一问流式返回 | P0 |
| FR-I5 | 两轮 persona | `tech → hr` 顺序；各自 system prompt 与 rubric；每轮题数上限可配（默认 8 / 6） | P0 |
| FR-I6 | 面试报告 | 每轮分数、综合结论（通过 / 待提升）、逐题回顾（问题 / 回答 / 评分 / 依据 / 更好的答法）、与简历薄弱点的关联 | P0 |
| FR-I7 | 中断续答 | 状态在 DB，刷新可继续；24h 无活动 → `abandoned` 并按已答题出报告 | P1 |
| FR-I8 | 异常处理 | 空答 / 跑题 / "跳过" → 面试官按策略处理（提示一次后换题）；单场成本上限 | P1 |
| FR-I9 | 语音 | 本期不做 | 未来工作 |

### H. 系统支撑

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-H1 | LLM / reranker 可插拔（注册表） | P0 |
| FR-H2 | Prompt 版本化常量，落库 `prompt_version` | P0 |
| FR-H3 | 调用审计：`llm/client.py` 唯一出口落库，缓存命中也记一行 | P1 |
| FR-H4 | 评测 CLI：`gen_eval_set.py` / `run_eval.py`（绕过缓存、`--repeat 3`） | P1 |
| FR-H5 | 数据种子：`scripts/seed.py` 幂等重建 skills 表、三个 collection、岗位模板 | P1 |

## 1.4 非功能需求

| 编号 | 指标 |
|---|---|
| NFR-1 性能 | 单份解析 < 3s（不含 LLM）；完整诊断 < 30s；面试每轮首字 < 3s、整轮 < 15s |
| NFR-2 准确性 | 版面合成集（N=60，3 种版面，仅 PDF）line 级相邻行对顺序准确率 ≥ 95%；残留幻觉率（人工复核）≤ 2% |
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
