# 四、AI 模块设计

## 4.1 AI 应用点

| # | 场景 | 时机 | 类型 | temp | 设计要点 |
|---|---|---|---|---|---|
| 1 | 章节归类兜底 | 解析期 | LLM | 0 | 词典认不出的候选标题（字号更大，或与词典标题同样式，见 5.4）一次送审，可判"不是标题" |
| 2 | 结构化抽取 | 解析期 | LLM | 0 | 按章节送带编号块；条目输出 `block_ids`；**basics 不送** |
| 3 | **语义诊断** ★ | 诊断期 | LLM | 0 | 单条目送审，json_mode，evidence 必须为子串 |
| 4 | JD 解析 | 匹配期 | LLM | 0 | 拆要求项 |
| 5 | **技能匹配判定** ★ | 匹配期 | LLM | 0 | 词典未命中的要求项一次送审；逐项输出 status + 逐字引用的简历原文，经 locate_span 校验 |
| 6 | 具体建议 | 点开时 | LLM | 0.3 | 简历问题：【问题】【改成】【为什么】；岗位差距：【考察什么】【怎么补】【面试怎么答】。流式输出纯文本；占位符 + 确定性复检；本期不检索（06-workflows 6.5） |
| 7 | **面试计划** ★ | 面试创建 | LLM | 0.7 | 输入：岗位要求 + 初筛判定、经历（掩码）、最多 6 条简历问题、不长的面经 → 5 个 topics，每个带来源编号（P / R / F），代码核对 |
| 8 | **回答评估** ★ | 每题 | LLM | 0 | rubric 结构化输出，evidence 逐字引用回答并经 locate_span 校验；参考答法里的新数字换成【数值】 |
| 9 | **下一问生成** ★ | 每题 | LLM | 0.7 | 输入：面试官设定（公司、岗位）、当前话题 + 材料、面经片段、本话题的问答与上一答的不足 → question（流式）；追问与否由评估的 decision + 代码规则决定 |
| 10 | 面试报告 | 面试结束 | LLM | 0.3 | 分数由确定性聚合，LLM 只写 strengths / weaknesses / 和简历问题的关联 |

不调模型的：版面重排兜底（理由见 5.1 末尾）、技能语义召回（词典未命中的要求直接交 #5 全文判定）、差距分析（就是匹配明细里 miss / partial 的要求，由 `GET /apply/{id}` 读取时排序组装）。

## 4.2 明确不用 AI 的地方

```
basics 抽取 / 规则诊断 / 证据校验 / 综合评分 / 时间归一化 / 分栏与表格 / 占位符复检
匹配：词典命中、学历、年限的判定与匹配度评分（模型只判规则判不了的要求，见 #5）
面试：话题推进、追问次数上限（1 次）、成本上限、分数聚合、通过判定 —— 全部确定性逻辑（只有技术面）
```

## 4.3 解析流水线

解析不在图里：上传时由 BackgroundTasks 触发 `parse_service.parse_resume`，步骤顺序见 [06-workflows](06-workflows.md) 6.2「解析」；各步算法见 5.1–5.6。

## 4.4 诊断工作流

诊断子图的节点（rule_scan → plan_review → review_unit × N → merge_findings → score）与三种 mode 见 [06-workflows](06-workflows.md) 6.2；State 见 `graphs/state.py` 的 `DiagnoseState`。
落库在图外（diagnose_service）：一次 `SELECT parsed_blocks` 映射 page_no/bbox；写 findings（含 failed 行）；统计首轮数；`status` 与 `resumes.overall_score` 同事务。

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
| 面试出题 | 只检索 `interview_ctx`：用户贴的面经超过 3000 字时切段，每个话题召回 → reranker 精排 top-3；简历、JD 不检索（整段给） | 下一问 LLM | ✅ |

改写、匹配都不检索（理由见 06-workflows 6.2、6.5）。

链路：**切块 → 向量化入库 → 召回（embedding）→ 精排（reranker，cross-encoder）→ 注入 prompt**。
实现在 `retrieval/context_store.py`（面经：切段、入库、召回、精排、会话结束删除）与 `llm/embedding.py`。简历单元的逐条检索只在 06-workflows 6.2 的对照实验里用过，代码已删除（见提交 ee10f38）。
为什么要两阶段：embedding 是双塔模型，query 与文档各自编码，快但粗；reranker 把 query 与每个候选拼在一起过模型，准但慢——所以先用前者把上千条缩到 20 条，再用后者挑 3 条。
reranker 失败或关闭时退化为直接取召回 top-3，功能不中断。

**"模拟某家公司"的信息来源**：LLM 不依赖对公司的先验记忆。必填 JD（用户粘贴）给出"这家公司要什么"；可选 `company_name` + `extra_context`（面经、公司/部门介绍）给出"这家公司怎么问"；没有 JD 时用内置岗位模板。面试官的 system prompt 显式写入这些材料。

## 4.7 隐私

```
basics         本地抽取，永不出现在任何 prompt
mask_pii       长度不变：手机号、身份证号数字→'X'，邮箱字符→'*'，姓名→等长的'某'；应用于所有外发的简历文本（mask_resume）
interview_ctx  会话 completed/abandoned 时删除该 session 的切块
cases / jd     仅公开数据（以后建案例库时，构建脚本不读 resumes 表）
清理           软删除 30 天后物理删除（未实现）；llm_calls 不存正文（评测也只多记一个 run_id）
```

## 4.8 成本、缓存、审计（llm/client.py 唯一出口）

```
client.invoke(scene, messages, prompt_version, schema?, ref?, model?, temperature, use_cache)  → LLMResult{text, parsed, parse_error, token, cost, cache_hit, model_version}：
  ① 渲染 prompt → key = llm:{scene}:{model}:{prompt_ver}:{sha256(rendered_prompt)}
  ② 缓存命中 → 记 llm_calls 一行（cache_hit=TRUE, token/cost=0）→ 返回      （面试 interview_plan / ask / eval / report 都不走缓存：每次对话都不同）
  ③ Redis 限流（按分钟固定窗口计数，DeepSeek 每分钟 300 次：官方不限速率，这里只防一次发太多）；Redis 不通或排队超时按调用失败处理，抛 LLMError
  ④ 调模型；token 取自 AIMessage.usage_metadata；cost 按单价表；取 system_fingerprint
  ⑤ 写缓存（TTL 7d）+ llm_calls 落库 → Result{parsed, raw, cost, tokens}
invoke_json(llm, scene, messages, schema, prompt_version, …) → (parsed | None, 两次总花费, 错误)：不合格时把上一次输出和原因（prompts.JSON_RETRY）发回去重试一次；
  结构化抽取 / 章节归类 / JD 解析 / 匹配用它；面试出题、评分、诊断重试前还要核对编号 / 证据 / 引用，自己写循环，只共用 JSON_RETRY
向量与重排走 llm/embedding.py 的 EmbeddingClient：同样限流、记账，不做结果缓存；失败抛 LLMError，调用方降级（rerank 失败退化为召回序）
评测模式：设了评测批次号（ContextVar current_run_id）⇒ 跳过缓存，llm_calls 每行带 run_id；评测脚本把汇总结果写 data/eval_runs/{task}-{时间}.json
```

成本（实测）：单份诊断约 ¥0.028（llm_only / hybrid，05 第 8.3 节）；单场面试 5 个话题、最多 10 问，一场 9 问约 ¥0.075；面试评分每次约 ¥0.0047（05 第 8.4 节）。

## 4.9 模拟面试

只有技术面：5 个话题，每个最多追问 1 次。创建 / 开始 / 作答 / 提前结束 / 放弃的流程、图 B 的节点和两份状态（MySQL 为准、SQLite 检查点续跑）只在 [06-workflows](06-workflows.md) 6.3 写；这里只放 prompt（4.10）和评分聚合（5.9）。

## 4.10 面试 Prompt 骨架（全文见 `llm/prompts.py` 的 `INTERVIEW_*`，版本 interview-v2）

```
[plan · temp 0.7，不走缓存]
为「{job_title}」定 {n} 个话题。每个指向材料里的一条：project（P 开头）/ requirement（R 开头，优先必须项里没满足或部分满足的）/ finding（F 开头）。
至少 1 个 project、2 个 requirement，finding 最多 2 个；先聊项目再到要求。label 14 字以内、中性；intent 40 字以内。
输出 {"topics": [{"source","ref","label","intent"}]}

[ask · temp 0.7，流式，不走缓存]
你是{company 或 "目标公司"}的技术面试官，面试「{job_title}」的实习生候选人。一次只问一个问题，60 字以内，口语化；
具体到做了什么、为什么、怎么验证；追问必须接住上一句回答里的某个说法；不评价、不透露评分；材料里没有的事不当成候选人做过的来问。
输入：话题 + 考察目标 + 相关材料（这条经历 / 要求 / 问题）+ 面经片段 + 本话题已问过的问答和评分员指出的不足
开场白（第一题前那句"你好，我是……今天大概聊 N 个话题"）由代码拼，不花模型的钱

[eval · temp 0，不走缓存]  correctness / depth / clarity 各 0–5；evidence 每段 6–40 字、逐字引用回答
输出 {"scores":{...},"evidence":["..."],"good":"...","bad":"...","better_answer":"...","decision":"followup|next"}
better_answer：以候选人口吻、150 字以内；回答里没有的数字 / 规模 / 结果用【】占位，不得编造

[report · temp 0.3，不走缓存]  strengths / weaknesses 各 1–3 条 {title, detail}；links 只写给列出的简历问题 / 岗位差距，ref 照抄编号
```

---

# 五、核心算法

## 5.1 region-first 分栏（PDF，实现见 `parser/layout.py`）

```
1  页眉页脚剔除：y 在页顶 / 页底 6% 内，且（匹配页码正则 或 多页同位置同文本）→ 删
2  表格区域：extract 用 find_tables() 取有边框表的格子位置（≥2 行 ≥2 列）；文字仍用抽出的行——find_tables 按格子边界裁字，
   超出格子的日期会被切成两半。中心落在表里的行归到重叠面积最大的格子；有字的格子 < 4 个或不到一半 → 不算表格
   （挡掉"顶部色条 + 侧边栏底色块"拼成的 2×2 假表格）。
   整张表缩成一个"替身行"参与第 3–6 步：压住中缝就是通栏，落在某一栏里就留在那一栏；落位时再按行展开：
     一行每格只有一行字 → 整行一块（格间空一格）；第一格是标签（在最左列、≤ 8 字，且这一行只有两格而右格更长，
     或它竖着合并了好几行）→ 标签先单独成块（表格型简历的章节名在左列，拆开章节识别才认得出）；
     有格子写了多行 → 每格各自是一个叶子（右边界取格子边框），照常拼折行、按项目符号分块。
   不加表格识别时，列间空白会被当成栏间空白，整张表按列读乱，页面还被判成 sidebar、置信度 1.0（2026-09-27 实测）
3  找栏间空白带：宽 3%·W 的竖直窗口滑过区域，取"压住它的行最少"的位置；c = 1 − 压住的行数 / 区域行数。
   空白带两侧都要像一栏（每侧 ≥ 3 行、字数 ≥ 12%），否则不算——挡掉右对齐的日期这类假右栏。
   时间轴不切：去掉跨栏行后，较少一侧过半是日期行（日期占该行一半以上，「2022 年 优秀学生干部」不算），且这些日期 ≥ 80% 和另一侧某行同一水平线
   → 左列日期、右边经历，按行读（日期跟着它那条经历）。只看"两侧对不对齐"不行：正常两栏行距一样，左右也常对得很齐（合成集最高 0.94）
4  c ≥ 0.8 → 分栏：压住空白带的行是跨栏行（通栏标题、页顶姓名，column_index=-1），用它们把区域横切成几段、各段再处理；
   没有跨栏行就左右切开，先读左栏再读右栏（递归，深度 ≤ 6）
5  切不动 → 在 ≥ 1.5 倍行高的水平留白处横切，每段再试一次第 3 步
6  仍切不动 → 叶子：同一水平线的片段合并成一行，按 y、x 排序；0.3 < c < 0.8 的叶子记为 unknown
7  页级结果：表格字数占全页 ≥ 70% → table（1.0）；unknown 行占全页 ≥ 30% → unknown（0.5）；分栏行占 ≥ 30% → 空白带中心在 40%–60% 页宽内为 double、否则 sidebar，
   置信度取切分时最小的 c；其余为 single（1 − 最像有空白带的那个叶子的 c）
8  分块：叶子内把折行并回同一块；遇项目符号、标题样式、明显留白、"标签：内容"列表的下一项、由相隔较远的几段拼成的行（「日期 …… 标题」）另起一块
简历级：layout_type 取第 1 页；confidence 取各页最小；layout_detail 逐页
常数：6% / 3% / 0.3 / 0.8，写进 config
```

**为什么不做 LLM 版面兜底**（原设计：unknown 页的块编号交 LLM 重排，只回序号）。2026-10-06 用几种难版式实测原触发条件（unknown 行 ≥ 30%，即置信度 < 0.7）：

| 版式 | 规则读得对吗 | 规则自报 | 会触发兜底吗 |
|---|---|---|---|
| 时间轴（左列日期） | 错 | sidebar 1.0 | 不会（漏报） |
| 无边框表格 | 对 | unknown 0.5 | 会（误报） |
| 两栏（间距 24 / 12pt） | 对 | double 1.0 | 不会 |
| 三栏技能 | 错（按行读了） | unknown 0.5 | 会 |

最常见的错是"有把握地读错"，兜底触发不了；能触发的三栏技能，按行读对后面抽技能也没影响。所以改用规则修时间轴（第 3 步），不做模型兜底；
`layout_confidence` 保留为规则的自我评估，只作记录。
## 5.2 full_text 契约与 locate_span

```
full_text = "\n".join(b.text for b in blocks_by_index)；char_end 开区间；下一块 start = 上一块 end + 1
单位：Unicode 码点；extract 阶段非 BMP → U+FFFD ⇒ Python len == JS .length
冻结：偏移算出后不得再 strip / 折叠空白 / NFC / 全半角转换
匹配用归一化（长度不变）：全角标点→半角一对一，\n \t → 空格

locate_span(quote, text, hint=(lo,hi)) -> (start, end, score) | None
  text[lo:hi] 上：① str.find → 1.0  ② rapidfuzz partial_ratio_alignment ≥ 90 → 对齐区间
  都失败 → 全文再 ①②；返回全局偏移；None 即不可定位
用途（5 处调用）：诊断 evidence（llm_review，hint=条目区间）、JD 解析的要求原话（jd_parser）、匹配的简历依据（llm_judge）、
      结构化抽取的技能名（structure，hint=块区间）、面试评分 evidence（rubric，text=回答）；规则引擎的证据本来就是原文切片，不用核对
```

## 5.4 章节识别

8 类：`basics / summary / education / work / projects / skills / awards / other`。词典匹配：整行==别名 → 中英双语（中文部分、英文部分各自是别名）→ 组合标题按 与 / 及 / 和 / & / 、 / 斜杠 拆开，每部分都是别名则取第一部分的类型（「专业技能与证书」→ skills；拆之前先去掉「一、」这类编号）。
词典 2026-09-28 补过一轮：9-27 实测漏掉的 14 个（项目展示、开发经历、工作履历、校园活动、技能证书、技术专长、主修课程……）及同类常见写法。有歧义的归法：主修课程 → education、实习项目 → projects、技能证书 → skills。

| 特征 | 分值 |
|---|---|
| 词典命中 | +3 |
| 字号 ≥ 正文中位数 × 1.1（实测常见组合：正文 10.5 / 标题 12，比值 1.14） | +1 |
| 加粗 | +1 |
| 孤行且 ≤ 12 字 | +1 |
| 上方留白 ≥ 0.6 倍行高（正常行间留白约 0.1–0.3 倍；页 / 栏的第一块视为有留白） | +1 |

分 ≥ 3 判标题；`confidence = min(1, 分/5)`。双语标题要求「中文部分 + 英文部分」恰好拼出整行且各自都是别名（「技术栈：SpringBoot」「项目经历 2024」不算）。
词典未命中的候选（记为 other 并标 `needs_llm`）：出现在第一个词典标题之后（页顶大号姓名属于 basics）、≤12 字、不以冒号结尾（「核心业务开发：」是项目内小标题）、不以项目符号开头，且满足其一：
- `feature`：字号 ≥ 正文 × 1.1 且得分 ≥ 3；
- `style`：和某个词典标题同字号、同粗细，且这个样式和正文不同（标题与正文一样大、只是加粗的简历靠这条；标题与正文完全同样式时不找候选）。

**LLM 归类**（`parser/section_llm.py`，scene=section，prompt `SECTION_*` section-v1，temp 0、走缓存）：全部候选一次发出，每个带标题 + 下面内容前 80 字（先 PII 掩码）+ 已认出的词典标题作参考；
模型给每个候选选 education / work / projects / skills / awards / summary / other / none。只认编号和类别，其余按"没回答"处理；输出不合格重试一次。
none（项目名、公司名）→ 并回上一节；其余 → matched_by=llm。没回答或调用失败 → 同不调模型：feature 仍是 other + needs_llm，style 并回上一节；失败原因写进 `structure.extraction_errors`，不算解析失败。
实测一次约 ¥0.002、1.8 秒。

**没有标题的教育**：全文没有 education 章节时，开头段（第一个标题之前）末尾连续的"像教育"的块（含「××大学 / ××学院」或本科、硕士等学历词，且不含电话、邮箱、住址——「海淀区学院路」「大学城」也会命中学校名）切出来作为 education（matched_by=implicit）。
只切末尾：放在前面的电话邮箱仍留在 basics，basics 不发给模型。结构化抽取的 prompt 里这一节称「教育经历」。表格型简历的教育表常常没有标题，就靠这条。

不处理：全文一个词典标题都没有（整篇 other，分不清标题和页顶姓名）；标题与正文完全同样式（同字号、都不加粗，只能靠颜色区分，而抽取没有记颜色）。

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
     只在十拿九稳时下结论：要求去掉技能名后不超过 6 个字（"熟悉 Redis"），且该技能出现在工作 / 项目经历里；
     带限定语的（"熟悉 Redis 缓存穿透…"）或只列在技能清单里的，留给模型
  ② 学历 / 年限：要求里写了学历层次或"N 年"，与简历的最高学历、工作与实习总时长比；matched_by='profile'
  ③ 模型路：其余要求项连同掩码后的简历全文一次交给 LLM，逐条输出 {status, evidence_quote, reason}；
     hit/partial 的 evidence_quote 须经 locate_span 定位，定位失败 → 计入 hallucination_count 并按 miss；matched_by='fulltext'
  mode：dict_only / llm_fulltext / hybrid，见 06-workflows 6.2（匹配不用 RAG 的原因也在那里）
为什么不建本体树：上下位知识（Spring Boot 属于 Java 生态）LLM 本来就有，手工建树覆盖面永远不够；
  词典只保留「同一技能的不同写法」这种确定性最高、LLM 也无需判断的部分。与诊断模块同一原则：确定的先上，模糊的交给 LLM，LLM 输出必须可验证。
degree_level(structure)∈{0..4}；experience_years(structure) = work[] 区间合并求和
```

## 5.7 综合评分（诊断）

```
dim_score[d] = max(0, 100 − Σ penalty)，high 25 / medium 12 / low 5；无来源维度 null
权重 0.25 / 0.25 / 0.20 / 0.20 / 0.10；overall 只对非 null 维度加权归一
扣分按经历条数摊薄：4 条以内不摊薄，超过的按 4 / 条数缩放（经历多的简历被查的地方也多）
```

## 5.8 改写占位符复检（`rewrite/advice.py`）

```
mask_new_numbers(text, original)：用 rules.NUMBER（与规则"有没有数字"同一口径，排除 Vue3、CET-6 这类名称与版本号）找数字，
  original 里没出现过的换成【数值】，返回 (新文本, 换掉的个数)；【】里的占位不动
fix_numbers(text, section, original)：按【段标题】切开，只对【改成】（问题）/【怎么补】（差距）一段调 mask_new_numbers；
  换掉的个数记为 violation_count，存进 findings.rewrite / items[k].advice
面试的参考答法也用 mask_new_numbers（keep_digits=True：放过一位数，"影响行数为 0" 这类技术细节不算编造）
不重试：流式输出已经显示出去的字撤不回来，所以直接替换，以复检后的全文为准存库、在 done 事件里下发
```

## 5.9 面试评分聚合（确定性，`interview/rubric.py`）

```
每题分 = mean(rubric 三维) × 20（0–100）；跳过的题记 0 分；low_evidence 的题权重 0.5
话题分 = 该话题各题分的加权平均（追问题计入）；没问到的话题为空
综合   = 问到了的话题的平均
verdict：练习模式 → practice；没聊完所有话题就结束 → incomplete（不下结论）；否则综合 ≥ 60 → pass，不然 fail
links（和简历问题的关联）= 得分 < 60、来源是简历问题或岗位要求的话题
```

## 5.10 求职方向（领域包，`app/domains/`）

同一套流程（解析 → 诊断 ∥ 匹配 → 初筛 → 建议 → 面试）服务不同专业：工作台第一步选方向（计算机 / 运营……），
方向存在岗位上（`jobs.domain`），之后各环节按岗位的方向取一个「领域包」。**加一个方向 = 加一套规则和数据，流程代码不改。**

```
领域包（domains/cs.py、ops.py）
  TEXTS          提示词里随方向变化的 25 处片段：招聘官 / 面试官角色、JD 解析的技能说明、评分的「正确性」定义、各处示例 JSON
  DISABLED_RULES 这个方向不跑的规则（如设计类可关掉「技能要在项目里用过」）
  页面文案       名称、图标、一行说明、诊断标准 / 面试内容提示、技术面 / 运营面、示例 JD（GET /domains 给前端）
```

- **哪些不进领域包**：简历解析（上传时还不知道投哪个岗位，章节词典、结构化抽取只能是全集）；技能词典（不同专业的词不冲突，
  新方向的词直接加进 `skills_seed.csv`，类别写新的）。
- **怎么换提示词**：`prompts.py` 里随方向变化的地方写成 `[[名字]]`，拼好提示词的最后一步由 `domains.fill()` 换成领域包里的文字。
  放在 `.format()` 之后换，领域包里的示例 JSON 不用管花括号转义；缺了某个片段直接 `KeyError`，不会把标记发给模型。
- **计算机方向逐字不变**：`cs.py` 的片段是从改造前的提示词里用脚本逐字截出来的；`tests/prompt_cases.py` 按真实调用路径生成 10 个场景的提示词，
  `test_domains.py` 和改造前的快照逐字比对。所以提示词版本号不用升，缓存不失效，M8 的评测数字仍然对应现在的代码。
- **加一个方向的步骤**：照 `cs.py` 写 `domains/<key>.py`（片段要和 cs 一一对应，测试会查）→ 在 `DOMAINS` 登记 → `skills_seed.csv` 加词条
  → `data/job_templates/<key>/*.txt` 写模板 → `build_job_templates.py`（只解析新的或改过的模板）→ `dump_seed.py` → 导入 seed.sql。
- 现状：计算机（默认）+ 运营两个方向；运营 2 份模板、36 个词条。运营另有一套评测集（05 8.3 (7)）：同一批运营简历用两种包跑，检出率、一致率差不多，差别在说法（计算机包会说"技术含量"）。

---

# 六、后端设计


## 6.1 分层与目录

```
api/        路由层 —— 薄
services/   业务层 —— 流程编排、事务、DB；面试状态机在 interview_service
parser/ diagnose/ matching/ interview/ graphs/   领域层 —— 纯逻辑

（逐文件说明见 07-代码导读）

backend/app/
├── main.py（lifespan：检查 MySQL / Redis、启动清理）  config.py  database.py  deps.py  errors.py  security.py
├── models.py（11 张表）  schemas.py
├── api/        auth.py resume.py diagnose.py job.py match.py apply.py task.py system.py advice.py interview.py
│               sse.py（SSE 拼装，进度流 / 具体建议 / 面试共用）
├── services/   resume_service.py parse_service.py diagnose_service.py job_service.py match_service.py
│               apply_service.py skill_service.py advice_service.py interview_service.py
├── parser/     extract.py layout.py ★ section.py section_llm.py（候选标题交模型归类） structure.py normalize.py pii.py
├── diagnose/   rules.py evidence.py ★ llm_review.py scorer.py types.py
├── rewrite/    advice.py（具体建议：拼 prompt、数字占位符复检）
├── matching/   skill_dict.py ★（extract_mentions） jd_parser.py matcher.py ★ llm_judge.py
├── interview/  materials.py（面试材料与编号） planner.py（定话题） asker.py（出题 prompt） rubric.py（评分与聚合） policy.py（推进规则） report.py（报告）
├── retrieval/  chroma_client.py context_store.py（面经切段检索）
├── graphs/     state.py apply_graph.py（图 A） diagnose_graph.py match_graph.py interview_graph.py（图 B） checkpoint.py（SqliteSaver）
├── llm/        client.py ★ registry.py prompts.py（随方向变化处写成 [[名字]]） audit.py embedding.py
├── domains/    求职方向（领域包）：__init__.py（Domain、fill） cs.py ops.py（见 5.10）
└── cache/      redis_client.py llm_cache.py ratelimit.py pubsub.py

后台任务直接用 FastAPI BackgroundTasks，入口在 parse_service.parse_resume 与 apply_service.run_apply；解析不在图里。

scripts/   dump_schema.py dump_seed.py build_job_templates.py gen_layout_set.py eval_layout.py gen_eval_set.py run_eval.py interview_answers.py
data/      skills_seed.csv job_templates/ job_templates.json resumes/ uploads/ chroma/ checkpoints.sqlite eval_runs/ layout_set/ eval_set/
tests/     每个模块一个 test_*.py（369 个用例，模型 / 向量库 / Redis / 检查点全部打桩，不联网）

frontend/src/
├── pages/       Home（首页 + 登录）  Workbench（新的投递：选岗位 → 选简历 → 投递）  ApplyResult（初筛结果，含"进入面试 / 练习模式"入口）
│                InterviewSetup（面试准备）  Interview★（流式对话）  InterviewReport
├── components/  JobPicker  ResumePicker  Pipeline（投递进度）  IssueItem  AdviceBlock（具体建议，流式）
│                ResumeSheet★（原文纸面，char 区间高亮）  Tabs  Headline  AppShell  effects  InterviewText（下划线、占位）
└── store/ api/ hooks/
```

## 6.2 Redis 职责与可用性约定

```
① 对话模型结果缓存（面试的调用不缓存；向量 / 重排不缓存）   ② 限流（按分钟固定窗口计数）   ③ 后台任务 SSE pub/sub
④ LangGraph checkpoint：不用 Redis；图 B 用 `SqliteSaver`（`data/checkpoints.sqlite`）
Redis 与 MySQL 同为必需依赖，启动 ping 失败即退出。运行期：llm_cache get/set 异常按 miss；
限流占位失败（Redis 不通、排队超时）按模型调用失败处理（LLMError），走各调用方的失败路径。
```

## 6.3 启动清理（lifespan，单进程，只跑一次）

```sql
-- pending 也算：后台任务是进程内 BackgroundTasks，进程一退出，还没开始的也永远不会跑了
UPDATE resumes            SET parse_status='failed', parse_error='interrupted' WHERE parse_status IN ('pending','parsing');
UPDATE diagnoses          SET status='failed', error_msg='interrupted'          WHERE status IN ('pending','running');
UPDATE match_reports      SET status='failed', error_msg='interrupted'          WHERE status IN ('pending','running');
-- 面试（interview_service.cleanup_idle）：未结束且 last_active_at < now-24h → 按已答题聚合报告（不调模型）→ abandoned；删检查点线程和 interview_ctx 切块
--   停在"等回答"是正常状态，不算中断，不在这里标失败
-- 〔未实现〕软删除 30 天：删文件 + DELETE resumes（CASCADE）
```

## 6.4 上传与存储 / 6.5 配置

上传按 01 FR-B1 的顺序校验（只收 PDF）、UUID 落盘、不挂 StaticFiles、同用户同文件去重。
配置：`pydantic-settings` 读 `.env`，阈值与常数集中在 `config.py`，仓库只提交 `.env.example`。
