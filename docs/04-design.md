# 四、AI 模块、核心算法与后端设计

> 本文只写各环节内部怎么做：算法、提示词要点、公式与阈值。产品流程、两张图和 State 见 [06-workflows](06-workflows.md)；
> 评测数字与实验结果见 [05-evaluation-and-plan](05-evaluation-and-plan.md)；逐文件说明见 [07-代码导读](07-代码导读.md)。
> 提示词全文以 `backend/app/llm/prompts.py` 为准，这里只写骨架和关键约束。

## AI 模块

### 4.1 AI 应用点

| # | 场景 | 时机 | 类型 | temp | 设计要点 |
|---|---|---|---|---|---|
| 1 | 章节归类兜底 | 解析期 | LLM | 0 | 词典认不出的候选标题（字号更大，或与词典标题同样式，见 4.10）一次送审，可判"不是标题" |
| 2 | 结构化抽取 | 解析期 | LLM | 0 | 按章节送带编号块；条目输出 `block_ids`；**basics 不送** |
| 3 | **语义诊断** ★ | 诊断期 | LLM | 0 | 逐条经历描述送审（掩码文本），json_mode，evidence 必须能在这条描述里逐字定位（4.3） |
| 4 | JD 解析 | 匹配期 | LLM | 0 | 拆要求项；每条带 JD 原话，经 locate_span 核对（4.12） |
| 5 | **技能匹配判定** ★ | 匹配期 | LLM | 0 | 规则判不了的要求项一次送审；逐项输出 status + 逐字引用的简历原文，经 locate_span 校验 |
| 6 | 具体建议 | 点开时 | LLM | 0.3 | 简历问题：【问题】【改成】【为什么】；岗位差距：【考察什么】【怎么补】【面试怎么答】。流式输出纯文本；占位符 + 确定性复检（4.14）；本期不检索（06-workflows 6.5） |
| 7 | **面试计划** ★ | 面试创建 | LLM | 0.7 | 输入：岗位要求 + 初筛判定、经历（掩码）、最多 6 条简历问题、不长的面经 → N 个（默认 5）topics，每个带来源编号（P / R / F），代码核对；能用的不够 N 个就带原因重试一次 |
| 8 | **回答评估** ★ | 每题 | LLM | 0 | rubric 结构化输出，evidence 逐字引用回答并经 locate_span 校验；参考答法里的新数字换成【数值】 |
| 9 | **下一问生成** ★ | 每题 | LLM | 0.7 | 输入：面试官设定（公司、岗位）、当前话题 + 材料、面经片段、本话题的问答与上一答的不足 → question（流式）；追问与否由评估的 decision + 代码规则决定 |
| 10 | 面试报告 | 面试结束 | LLM | 0.3 | 分数由确定性聚合（4.15），LLM 只写 strengths / weaknesses / 和简历问题的关联 |

所有 `[[…]]` 标记处按岗位的求职方向换成领域包里的文字（4.16）。

### 4.2 不用 AI 的地方；解析、诊断、面试的流程见 06

```
解析：basics 抽取 / 分栏与表格 / 章节词典 / 时间归一化 / 技能词典扫描
      版面不做大模型兜底（理由与实测见 05-evaluation-and-plan 5.2）
诊断：规则引擎 / 证据校验 / 综合评分
匹配：词典命中、学历、年限的判定与匹配度评分（模型只判规则判不了的要求，见 #5）
      不做技能语义召回：词典没命中的要求直接交 #5 全文判定
      差距分析就是匹配明细里 miss / partial 的要求，由 GET /apply/{id} 读取时排序组装
建议：占位符复检
面试：话题推进、追问次数上限（1 次）、成本上限、分数聚合、通过判定 —— 全部确定性逻辑
```

- **解析**：不在图里，上传时由 BackgroundTasks 触发 `parse_service.parse_resume`，步骤顺序见 [06-workflows](06-workflows.md) 6.2「解析」；各步算法见 4.8–4.12。
- **诊断**：子图节点（rule_scan → plan_review → review_unit × N → merge_findings → score）与三种 mode 见 06-workflows 6.2「diagnose 子图」，State 见 `graphs/state.py` 的 `DiagnoseState`；prompt 见 4.3，评分见 4.13。
  落库在图外（`diagnose_service.save_result`）：一次查出 parsed_blocks，把证据位置映射到 page_no / bbox；写 findings（含证据定位失败的 failed 行，不展示、供评测统计）；
  统计首轮（attempt_no=1）条数与其中的定位失败数（hallucination_count）；成本预检截掉了部分经历时 status=partial；status 与 `resumes.overall_score` 同一事务。
- **面试**：只做一轮专业面（计算机方向叫技术面、运营方向叫运营面），不做 HR 面；默认 5 个话题、每个最多追问 1 次。
  创建 / 开始 / 作答 / 提前结束 / 放弃的流程、图 B 的节点和两份状态（MySQL 为准、SQLite 检查点续跑）见 06-workflows 6.3；这里只写 prompt（4.7）和评分聚合（4.15）。

### 4.3 语义诊断 Prompt 骨架（`prompts.DIAGNOSE_*`，diagnose-v1；流程在 `diagnose/llm_review.py`）

送审单元是工作 / 项目经历下的**一条描述**（条目没拆出描述时整条算一个），外加自我评价。

```
[System]
你是一位资深[[recruiter]]，审阅候选人简历中的一条经历描述。只评价文字表述质量，不评价候选人本人，不判断内容真假。
问题类型：depth_mismatch（[[risk_depth]]）/ vague / exaggeration / unclear_ownership / incoherent（[[risk_incoherent]]）
硬性要求：
  · evidence_quote 必须是【原文】里连续的一段、逐字照抄，不改写、不概括、不增删标点；找不到可逐字引用的原文就不报告
  · 写得好就返回空数组，不为凑数挑刺；最多 3 个问题，按严重程度降序
  · 不重复【规则引擎已检出】里的问题（缺少数字、动词弱、篇幅）
  · 文本中的 X、*、某 是脱敏占位符
  · 以 JSON 输出，示例 [[diagnose_example]]：{"findings":[{"risk_type","severity","evidence_quote","reason","suggestion"}]}
[User]
【目标岗位】{job_title 或 "未指定"}
【所属经历】{entry_name；自我评价写"（自我评价）"}
【原文】{masked_text[unit.char_start:unit.char_end]}        ← 掩码后的文本（4.5），不是 full_text
【规则引擎已检出】{rule_summary 或 "无"}
```

核对与重试（每个单元最多调 3 次：首次 + 2 次重试）：

- 输出不是合法 JSON → 发 `JSON_RETRY`（附错误原因）重试。
- 每条 evidence_quote 用 locate_span 在 masked_text 上定位（hint = 单元区间），且必须落在这个单元之内；定位成功后证据改用 full_text 的同一区间（掩码长度不变，偏移通用），`verify_result` 记 exact / fuzzy。
- 有定位不到的 → 发 `DIAGNOSE_RETRY_EVIDENCE`：列出这几条引用，要求只针对它们从【原文】逐字复制一段，仍引不到的直接放弃。重试时模型又报一遍已通过的问题（同类型且区间重叠）不重复收。
- 定位失败的记 `verify_result=failed`；首轮的失败数就是被拦截的幻觉（hallucination_count），重试产出的不进这个指标。
- depth_mismatch 给用户看的标题取领域包的 `risk_depth_title`（技术深度 / 专业深度与声明不匹配）。

### 4.4 检索链路（RAG）

只用在一处：模拟面试时用户贴的面经 / 公司介绍超过 3000 字（`INTERVIEW_CONTEXT_FULL_MAX`）。为什么匹配不用 RAG、检索用在哪，见 [06-workflows](06-workflows.md) 6.5。

链路：**切块 → 向量化入库 → 召回（embedding）→ 精排（reranker，cross-encoder）→ 注入 prompt**，实现在 `retrieval/context_store.py` 与 `llm/embedding.py`。

```
切块   按空行、编号、列表符号分段；短段合并，长段按 500 字硬切、相邻两段重叠 80 字
入库   bge-m3 向量化，存进 Chroma 的 interview_ctx 集合，metadata.session_id 区分会话；会话结束即删（4.5）
召回   每个话题用"话题名 + 考察目标"召回 top-20（RAG_RECALL_K）
精排   bge-reranker 取 top-3（RAG_TOP_K），交给出题 prompt
```

为什么要两阶段：embedding 是双塔模型，query 与文档各自编码，快但粗；reranker 把 query 与每个候选拼在一起过模型，准但慢——所以先用前者缩到 20 条，再用后者挑 3 条。

降级（功能都不中断）：向量化入库失败 → 改为截取面经前 3000 字整段使用；检索失败 → 这一题不带面经照常出题；reranker 失败 → 直接取召回顺序的前 3 段。

### 4.5 隐私

```
basics         本地正则抽取；结构化抽取、章节归类都不发 basics 章节
mask_pii       长度不变：手机号、身份证号的数字 → 'X'，邮箱里除 @ 和 . 以外的字符 → '*'，所在地 / 籍贯冒号后的地名、姓名 → 等长的'某'
               所有外发的简历文本都先掩码（mask_pii；已解析的简历用 mask_resume，姓名取 basics.name）：章节归类、结构化抽取、诊断、匹配判定、具体建议、面试材料都是；
               匹配判定和差距建议发的是掩码后的全文，basics 那几行也在内（电话、邮箱、身份证号、所在地 / 籍贯、姓名都已掩掉）
               偏移不变，所以在掩码文本上定位到的区间可以直接切原文
interview_ctx  会话结束（completed / abandoned）或创建失败时删除该 session 的切块
案例库         以后若建，只收公开数据（构建脚本不读 resumes 表）
llm_calls      不存正文（评测也只多记一个 run_id）
物理删除       软删除 30 天后物理删除〔未实现〕，见 4.18
```

### 4.6 成本、缓存、审计（都经 `llm/` 包：对话走 `client.py`，向量 / 重排走 `embedding.py`）

```
client.invoke(scene, messages, prompt_version, schema?, ref?, model?, temperature, use_cache)  → LLMResult{text, parsed, parse_error, token, cost, cache_hit, model_version}：
  ① 渲染 prompt（messages + schema 名 + temperature 序列化）→ key = llm:{scene}:{model}:{prompt_ver}:{sha256(rendered_prompt)}
  ② 缓存命中 → 记 llm_calls 一行（cache_hit=TRUE, token/cost=0）→ 返回      （面试 interview_plan / ask / eval / report 都不走缓存：每次对话都不同）
  ③ Redis 限流（按分钟固定窗口计数，DeepSeek 每分钟 300 次：官方不限速率，这里只防一次发太多）；Redis 不通或排队超时按调用失败处理，抛 LLMError
  ④ 调模型；token 取自 AIMessage.usage_metadata；cost 按单价表；取 system_fingerprint
  ⑤ 写缓存（TTL 7d；空内容、解析失败的不缓存）+ llm_calls 落库 → Result{parsed, raw, cost, tokens}
invoke_json(llm, scene, messages, schema, prompt_version, …) → (parsed | None, 两次总花费, 错误)：不合格时把上一次输出和原因（prompts.JSON_RETRY）发回去重试一次；
  结构化抽取 / 章节归类 / JD 解析 / 匹配用它；面试出题、评分、诊断重试前还要核对编号 / 证据 / 引用，自己写循环，只共用 JSON_RETRY
向量与重排走 llm/embedding.py 的 EmbeddingClient：同样限流、记账，不做结果缓存；失败抛 LLMError，调用方降级（4.4）
评测模式：设了评测批次号（ContextVar current_run_id）⇒ 跳过缓存，llm_calls 每行带 run_id；评测脚本把汇总结果写 data/eval_runs/{task}-{时间}.json
```

成本上限：诊断 `DIAGNOSE_COST_LIMIT` ¥0.05，plan_review 按每个单元 ¥0.002（`UNIT_COST_EST`）× 1.5（给重试留余量）预检，超出的单元不送审、诊断记为 partial；
面试 `INTERVIEW_COST_LIMIT` ¥0.3，到顶就提前结束并出报告（`interview/policy.py` 的 decide）。实测花费见 05-evaluation-and-plan 5.3（诊断、匹配）、5.4（面试）。

模型服务调不通（`llm/status.py`）：

```
认出来   client.py 把服务商的错误分成两类：402 余额不足 / 401、403 密钥无效 / 429、5xx 服务繁忙 / 连不上、超时 → LLMError.unavailable = 原因；
         其余（请求本身的问题等）unavailable = None。前一类再试也没用，页面上统一说「模型服务暂时不可用……」，后一类照旧「请稍后重试」
记下来   碰上前一类就把原因写进 Redis 的 llm:status（存 60 秒）；GET /system/llm 先看它，没有就问 DeepSeek 的 GET /user/balance
         （不花钱：is_available=false → 余额不足，401 → 密钥无效，连不上 → 连不上；超时 10 秒，连不上再试一次），结论同样存 60 秒；余额接口自己出状况按能用处理
页面上   登录后每个页面内容最上面一条横幅，每分钟问一次；投递失败时 error_msg 写成「模型服务不可用：<原因>」，结果页、我的投递按这个前缀单独说；
         简历解析时调不通记成 parse_error=llm_unavailable，投递等到它时也按模型服务不可用报（不叫用户换简历）
```

### 4.7 面试 Prompt 骨架（`prompts.INTERVIEW_*`，interview-v2）

`[[interviewer]]` 计算机方向为「技术面试官」、运营为「运营面试官」；`[[interview_name]]` 为「技术面试 / 运营岗面试」；其余标记同样按方向替换（4.16）。

```
[plan · temp 0.7，不走缓存]
System：你是一位资深[[interviewer]]，要为「{job_title}」岗位的[[interview_name]]定下 {n} 个话题。
  每个话题指向材料里的一条，ref 照抄编号：project（P 开头）/ requirement（R 开头，优先「必须」里初筛判为没满足或部分满足的）/ finding（F 开头）
  恰好 {n} 个、考察点不重复、同一段经历最多用一次；至少 1 个 project、2 个 requirement，finding 最多 2 个；先聊项目再到要求
  label 14 字以内、中性；intent 40 字以内；只能用材料里的内容。输出 {"topics": [{"source","ref","label","intent"}]}（示例 [[plan_example]]）
User：岗位要求（编号 [必须 / 加分] 内容 —— 初筛判定）+ 简历经历（掩码）+ 初筛发现的简历问题 + 不长的面经
代码核对：编号不存在或重复的丢掉；能用的不够 N 个（材料总条数不足 N 时按材料条数算）就带原因重试一次，取两次里能用的多的那次

[ask · temp 0.7，流式，不走缓存]
System：你是{company 或 "目标公司"}的[[interviewer]]，正在面试「{job_title}」岗位的实习生候选人。一次只问一个问题，60 字以内，口语化；
  具体到做了什么、为什么、怎么验证；换话题可用一句很短的过渡；追问必须接住上一句回答里的某个具体说法；
  不评价、不透露评分；材料里没有的事不当成候选人做过的来问
User：话题 + 考察目标 + 相关材料（这条经历 / 要求 / 问题，附候选人的经历名清单）+ 面经片段
  + 主问题：前面已聊过的话题；追问：本话题已问过的问答和评分员指出的不足
开场白（"你好，我是……的[[interviewer]]，今天大概聊 N 个话题"）由代码拼，不花模型的钱

[eval · temp 0，不走缓存]
System：你是[[interview_name]]的评分员。correctness（[[correctness]]）/ depth / clarity 各 0–5；候选人说不会 / 没做过时 correctness、depth 给 0–1
  evidence 1–3 段、每段 6–40 字、逐字引用回答；better_answer 以候选人口吻、150 字以内，只用回答里的事实和通用的[[knowledge]]，
  回答里没有的数字 / 规模 / 结果用【】占位，不得编造
  输出 {"scores":{...},"evidence":["..."],"good":"...","bad":"...","better_answer":"...","decision":"followup|next"}（示例 [[eval_example]]）
代码核对：evidence 一条都定位不到 → 发 INTERVIEW_EVAL_RETRY 重试一次 → 仍不行给中性 3 分、标 low_evidence（4.15）

[report · temp 0.3，不走缓存]
System：你是[[interviewer]]。strengths / weaknesses 各 1–3 条 {title, detail}；links 只写给列出的简历问题 / 岗位差距，ref 照抄编号（示例 [[report_example]]）
```

**"模拟某家公司"的材料从哪来**：模型不依赖对公司的先验记忆。岗位要求来自用户粘贴的 JD（或内置岗位模板）；公司名（创建面试时可填，默认取岗位上的公司）写进出题的面试官设定；
面经 / 公司介绍（选填的 `extra_context`）不超过 3000 字时整段进计划和出题的 prompt，更长才切段检索（4.4）。

## 核心算法

### 4.8 region-first 分栏（PDF，实现见 `parser/layout.py`）

```
1  页眉页脚剔除：y 在页顶 / 页底 6% 内，且（匹配页码正则 或 多页同位置同文本）→ 删
2  表格区域：extract 用 find_tables() 取有边框表的格子位置（≥2 行 ≥2 列）；文字仍用抽出的行——find_tables 按格子边界裁字，
   超出格子的日期会被切成两半。中心落在表里的行归到重叠面积最大的格子；有字的格子 < 4 个或不到一半 → 不算表格
   （挡掉"顶部色条 + 侧边栏底色块"拼成的 2×2 假表格）。
   整张表缩成一个"替身行"参与第 3–6 步（否则列间空白会被当成栏间空白，整张表按列读乱）：
   压住中缝就是通栏，落在某一栏里就留在那一栏；落位时再按行展开：
     一行每格只有一行字 → 整行一块（格间空一格）；第一格是标签（在最左列、≤ 8 字，且这一行只有两格而右格更长，
     或它竖着合并了好几行）→ 标签先单独成块（表格型简历的章节名在左列，拆开章节识别才认得出）；
     有格子写了多行 → 每格各自是一个叶子（右边界取格子边框），照常拼折行、按项目符号分块。
3  找栏间空白带：宽 3%·W 的竖直窗口滑过区域，取"压住它的行最少"的位置；c = 1 − 压住的行数 / 区域行数。
   空白带两侧都要像一栏（每侧 ≥ 3 行、字数 ≥ 12%），否则不算——挡掉右对齐的日期这类假右栏。
   时间轴不切：去掉跨栏行后，较少一侧过半是日期行（日期占该行一半以上，「2022 年 优秀学生干部」不算），且这些日期 ≥ 80% 和另一侧某行同一水平线
   → 左列日期、右边经历，按行读（日期跟着它那条经历）。只看"两侧对不对齐"不行：正常两栏行距一样，左右也常对得很齐
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

**版面不做大模型兜底**：规则最常见的错（时间轴）是"有把握地读错"，原定的触发条件（置信度 < 0.7）根本触发不了，所以改用规则修时间轴（第 3 步）；`layout_confidence` 只作为规则的自我评估记录。理由与实测见 05-evaluation-and-plan 5.2。

### 4.9 full_text 契约与 locate_span

```
full_text = "\n".join(b.text for b in blocks_by_index)；char_end 开区间；下一块 start = 上一块 end + 1
单位：Unicode 码点；extract 阶段非 BMP → U+FFFD ⇒ Python len == JS .length
冻结：偏移算出后不得再 strip / 折叠空白 / NFC / 全半角转换
匹配用归一化（normalize_for_match，逐字符一对一、长度不变）：
  全角 ASCII → 半角；中文标点（。、“”‘’【】《》—～·）→ 对应半角；\n \t \r、全角空格、不换行空格 → 空格；ASCII 大写（含全角 Ａ–Ｚ）→ 小写

locate_span(quote, text, hint=(lo,hi)) -> Span(start, end, score, method) | None
  quote 先去掉两端的空白、引号、省略号；归一化后不足 2 字 → None
  text[lo:hi] 上：① str.find → score 1.0、method=exact
                  ② 引用 ≥ 6 字时 rapidfuzz partial_ratio_alignment ≥ 90（EVIDENCE_FUZZY_MIN）→ 对齐区间、score = 得分 / 100、method=fuzzy
  都失败 → 全文再 ①②；返回全局偏移；None 即不可定位
  method 会落库：诊断 findings.verify_result、面试评分 evidence[].verify_result 记 exact / fuzzy（定位失败的诊断条目记 failed）
用途（5 处调用）：诊断 evidence（llm_review，text = 掩码全文，hint = 单元区间，且须落在单元内）、JD 解析的要求原话（jd_parser）、
      匹配的简历依据（llm_judge，text = 掩码全文）、结构化抽取的技能名（structure，hint = 块区间）、面试评分 evidence（rubric，text = 回答）；
      规则引擎的证据本来就是原文切片，不用核对
```

### 4.10 章节识别

8 类：`basics / summary / education / work / projects / skills / awards / other`。词典匹配：整行==别名 → 中英双语（中文部分、英文部分各自是别名）→ 组合标题按 与 / 及 / 和 / & / 、 / 斜杠 拆开，每部分都是别名则取第一部分的类型（「专业技能与证书」→ skills；拆之前先去掉「一、」这类编号）。
有歧义的归法：主修课程 → education、实习项目 → projects、技能证书 → skills。

| 特征 | 分值 |
|---|---|
| 词典命中 | +3 |
| 字号 ≥ 正文中位数 × 1.1（常见组合：正文 10.5 / 标题 12，比值 1.14） | +1 |
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

**没有标题的教育**：全文没有 education 章节时，开头段（第一个标题之前）末尾连续的"像教育"的块（含「××大学 / ××学院」或本科、硕士等学历词，且不含电话、邮箱、住址——「海淀区学院路」「大学城」也会命中学校名）切出来作为 education（matched_by=implicit）。
只切末尾：放在前面的电话邮箱仍留在 basics，basics 不发给模型。结构化抽取的 prompt 里这一节称「教育经历」。表格型简历的教育表常常没有标题，就靠这条。

不处理：全文一个词典标题都没有（整篇 other，分不清标题和页顶姓名）；标题与正文完全同样式（同字号、都不加粗，只能靠颜色区分，而抽取没有记颜色）。

### 4.11 时间归一化

```
先按「date 连接符 date」整体匹配（- – — ~ ～ 至 到 to），失败再单个 date
去空白后匹配；month 后 (?!\d) 且 1–12 校验
支持 2023.9 / 2023.09 / 2023/9 / 2023年9月 / Sep 2023 / 2023；至今/Present/现在 → end=null, is_present=true
两端精度不一致取粗；单个日期 end=null；失败整字段 null；输出 "YYYY-MM" 或 "YYYY"
```

### 4.12 技能提及抽取与「词典 + LLM」匹配

```
annotate_skills(structure, full_text, sections, skills)（解析最后一步，matching/skill_dict.py）：
  ① skill_mentions：词典的 canonical + aliases 编成正则（长度降序；英文写法两侧不能紧挨字母数字；≤ 2 字符的英文写法区分大小写，其余忽略大小写）
     扫 full_text，重叠时取更长的写法，按 sections 标 section_type；纯本地、无 API；词典里没有的词不产生 mention，不影响后续 LLM 判定
  ② 回填 skills[].skill_id 与 work / projects 各条目 tech_stack[].skill_id：按名字查词典，查不到留 null

JD 解析（jd_parser）：模型拆出要求项，每条带 JD 原话 quote；quote 经 locate_span 定位不到、或声称的技能在 JD 里没出现 → 丢弃并计数；
  技能名查词典回填 skill_id；同一技能只留第一次；最多 25 条；权重按 req_type 由代码定：hard 1.0 / plus 0.5 / soft 0.3

JD 要求项 ↔ 简历：
  ① 词典路（确定、免费）：要求项有 skill_id 且 skill_mentions 中存在同 skill_id → 出现在工作 / 项目经历里为 hit，只在技能清单里为 partial；
     matched_by='dict'，证据取该 mention 所在的那一行（过长截到 80 字）
     hybrid 下只在十拿九稳时下结论：判为 hit，且要求去掉技能名后不超过 6 个字（"熟悉 Redis"）；
     带限定语的（"熟悉 Redis 缓存穿透…"）或只列在技能清单里的，留给模型（dict_only 基线则词典能判的全判）
  ② 学历 / 年限：matched_by='profile'
     学历：层次分四档（博士 4 / 硕士 3 / 本科 2 / 大专 1 / 没有 0）。要求的门槛取要求里提到的**最低**一档（"本科或硕士在读" = 本科），
           先只看 content，content 没写学历才看 quote（原话里常带"硕士优先"）；简历取各条 education 的 degree 中最高的；简历 ≥ 门槛 → hit，否则 miss
     年限：要求里写了"N 年"或"N-M 年"（取下限 N）；紧挨在别的数字后面的不算（"2026年毕业"），N 超过 15 也不判，都交给模型；experience_years(structure, today) = work[] 中工作与实习（排除 kind=campus）的区间合并后求和，
           至今的算到 today，日期不完整的跳过；≥ N → hit，≥ N/2 → partial，否则 miss
  ③ 模型路：其余要求项连同掩码后的简历全文一次交给 LLM，逐条输出 {status, evidence_quote, reason}；
     hit/partial 的 evidence_quote 须经 locate_span 定位，定位失败 → 计入 hallucination_count 并按 miss；模型漏答的也按 miss；matched_by='fulltext'
  ④ 技能栏复核（hybrid，recheck_listed_only）：词典知道这项技能只出现在经历以外（①会判 partial）、模型却判 hit，
     且依据不和任何一段 work / projects 条目重叠 → 改用①的结论（partial，matched_by='dict'）；依据落在经历里的照模型的。
     模型常因"专业技能中列出了 X"判满足，和提示词里"只是提到 = 部分满足"相反（05 5.3 (2)）
匹配度 = 100 × Σ(weight × v) / Σ weight，v：hit 1 / partial 0.5 / miss 0；另按 skill / education / experience / other 各算一个（JD 里没有这类要求 → null）
初筛：匹配度 ≥ SCREEN_THRESHOLD（60）通过（图 A 的 gate）
mode：dict_only / llm_fulltext / hybrid 见 06-workflows 6.2「match 子图」；为什么不用 RAG 见 06-workflows 6.5
为什么不建本体树：上下位知识（Spring Boot 属于 Java 生态）LLM 本来就有，手工建树覆盖面永远不够；
  词典只保留「同一技能的不同写法」这种确定性最高、LLM 也无需判断的部分。与诊断模块同一原则：确定的先上，模糊的交给 LLM，LLM 输出必须可验证。
```

### 4.13 综合评分（诊断）

```
dim_score[d] = max(0, 100 − Σ penalty × scale)，penalty：high 25 / medium 12 / low 5；只算通过证据校验的 finding
scale = 4 / max(送审单元数, 4)：4 个以内不摊薄，超过的按比例缩放（经历写得多的简历被查的地方也多）
五个维度与权重：completeness 0.25 / quantification 0.25 / expression 0.20 / consistency 0.20 / ats 0.10
本次 mode 下没有来源的维度为 null（llm_only 只有 expression、consistency）；overall 只对非 null 维度加权归一
```

### 4.14 占位符复检（`rewrite/advice.py`）

```
mask_new_numbers(text, original)：用 rules.NUMBER（与规则"有没有数字"同一口径，排除 Vue3、CET-6 这类名称与版本号）找数字，
  original 里没出现过的换成【数值】，返回 (新文本, 换掉的个数)；【】里的占位不动
fix_numbers(text, section, original)：按【段标题】切开，只对【改成】（问题）/【怎么补】（差距）一段调 mask_new_numbers；
  换掉的个数记为 violation_count，存进 findings.rewrite / items[k].advice
面试的参考答法也用 mask_new_numbers（keep_digits=True：放过一位数，"影响行数为 0" 这类技术细节不算编造）
不重试：流式输出已经显示出去的字撤不回来，所以直接替换，以复检后的全文为准存库、在 done 事件里下发
```

### 4.15 面试评分聚合（确定性，`interview/rubric.py`）

```
每题分 = mean(rubric 三维) × 20（0–100）；跳过的题记 0 分；low_evidence 的题权重 0.5
话题分 = 该话题各题分的加权平均（追问题计入）；没问到的话题为空
综合   = 问到了的话题的平均
verdict：练习模式 → practice；没聊完所有话题就结束 → incomplete（不下结论）；否则综合 ≥ 60 → pass，不然 fail
links（和简历问题的关联）= 得分 < 60、来源是简历问题或岗位要求的话题
```

### 4.16 求职方向（领域包，`app/domains/`）

同一套流程（解析 → 诊断 ∥ 匹配 → 初筛 → 建议 → 面试）服务不同专业：工作台第一步选方向（计算机 / 运营 / 财会金融 / 其他），
方向存在岗位上（`jobs.domain`），之后各环节按岗位的方向取一个「领域包」。**加一个方向 = 加一套规则和数据，流程代码不改。**

```
领域包（domains/cs.py、ops.py）
  TEXTS          25 个键：24 个对应 prompts.py 里的 [[标记]]（招聘官 / 面试官角色、JD 解析的技能说明、评分的「正确性」定义、各处示例 JSON……）；
                 另 1 个 risk_depth_title 不是提示词片段，是 depth_mismatch 问题给用户看的标题
  DISABLED_RULES 这个方向不跑的规则（rule_code，如设计类可关掉 SKILL_PROJECT_MISMATCH「技能要在经历里用过」）；计算机、运营目前都为空
  RESULT_WORDS   规则判断「写没写结果」时，在通用结果词（提升、降低、缩短……偏技术）之外这个方向还认的词；计算机为空，
                 运营 21 个，只收指标名（涨粉、阅读量、转化率、留存率、GMV……），不收单独出现时多半在说做了什么的「留存、转化」
  页面文案       名称、图标、一行说明、诊断标准 / 面试内容提示、面试称呼（技术面 / 运营面）、示例 JD（GET /domains 给前端）
  NOTE           「结果可能不够准」的提醒，只有通用包有；前端有就显示（选方向的说明框、结果页分数卡、诊断报告），专门方向不写
```

- **哪些不进领域包**：简历解析（上传时还不知道投哪个岗位，章节词典、结构化抽取只能是全集）；技能词典（不同专业的词不冲突，
  新方向的词直接加进 `skills_seed.csv`，类别写新的）。
- **怎么换提示词**：`prompts.py` 里随方向变化的地方写成 `[[名字]]`，拼好提示词的最后一步由 `domains.fill()` 换成领域包里的文字。
  放在 `.format()` 之后换，领域包里的示例 JSON 不用管花括号转义；缺了某个片段直接 `KeyError`，不会把标记发给模型。
- **计算机方向逐字不变**：`cs.py` 的片段是从原提示词里用脚本逐字截出来的；`tests/prompt_cases.py` 按真实调用路径生成 10 个场景的提示词，
  `test_domains.py` 和快照逐字比对。所以引入领域包不需要升提示词版本、缓存不失效，评测数字仍然对应现在的代码。
- **加一个方向的步骤**：照 `cs.py` 写 `domains/<key>.py`（片段要和 cs 一一对应，测试会查）→ 在 `DOMAINS` 登记 → `skills_seed.csv` 加词条
  → `data/job_templates/<key>/*.txt` 写模板 → `build_job_templates.py`（只解析新的或改过的模板）→ `dump_seed.py` → 导入 seed.sql。
- 现状：计算机（默认）、运营、财会金融三个方向。运营 5 份模板（内容、用户、活动、电商、产品）、51 个词条；财会 4 份模板（会计、审计、财务分析、行业研究）、35 个词条（软件和业务方法，**证书不进词典**：证书多半写在「技能证书」一栏，解析时归到技能，「技能栏写了、经历里没用过」这条规则会对每个证书报一次；JD 里的证书要求记成 other，交给模型判断）。两套评测集的结果见 05-evaluation-and-plan 5.3 (7)(8)。
- 「其他」（`general.py`，通用包）：方向少，别的专业（设计、教育、法律、医药……）也要能测，就给一个不带行业的包兜底，排在下拉框最后。说法写成中性的（招聘官 / 面试官，示例用办公软件、毕业设计、职业资格证），结果词取运营和财会的并集，没有模板；规则照常跑，模型只凭常识和岗位原文判断，所以页面上明说「可能不够准，仅供参考」。和专门包差多少见 05 5.3 (9)。

## 后端设计

目录与各文件说明见 [07-代码导读](07-代码导读.md)。

### 4.17 Redis 职责与可用性约定

```
① 对话模型结果缓存（面试的调用不缓存；向量 / 重排不缓存）   ② 限流（按分钟固定窗口计数）   ③ 后台任务 SSE pub/sub
④ LangGraph checkpoint：不用 Redis；图 B 用 `SqliteSaver`（`data/checkpoints.sqlite`）   ⑤ 模型服务状态 llm:status（60 秒，4.6）
Redis 与 MySQL 同为必需依赖，启动 ping 失败即退出。运行期：llm_cache get/set 异常按 miss；
限流占位失败（Redis 不通、排队超时）按模型调用失败处理（LLMError），走各调用方的失败路径。
```

### 4.18 启动清理 + 每小时收尾放弃的面试

后台任务用进程内的 FastAPI BackgroundTasks，所以服务必须单进程运行（`--workers 1`）；启动那一刻库里"进行中"的任务必然是上次进程留下的，可以直接标失败。

```sql
-- 启动时（lifespan 的 cleanup_interrupted_tasks）跑一次。pending 也算：进程一退出，还没开始的也永远不会跑了
UPDATE resumes            SET parse_status='failed', parse_error='interrupted' WHERE parse_status IN ('pending','parsing');
UPDATE diagnoses          SET status='failed', error_msg='interrupted'          WHERE status IN ('pending','running');
UPDATE match_reports      SET status='failed', error_msg='interrupted'          WHERE status IN ('pending','running');
-- 面试（interview_service.cleanup_idle）：status 为 planned / in_progress，且 last_active_at（没有则 created_at）早于 now − 24h（INTERVIEW_IDLE_HOURS）
--   → 按已答题聚合报告（不调模型）→ abandoned；删检查点线程和 interview_ctx 切块
--   停在"等回答"是正常状态，不算中断，不在这里标失败
--   启动时跑一次；之后 main.py 的 sweep_forever 每小时（IDLE_SWEEP_SECONDS = 3600）再跑一次，服务长期不重启也能收尾；某轮失败只记日志，等下一轮
-- 〔未实现〕软删除 30 天：删文件 + DELETE resumes（CASCADE）
```

### 4.19 上传与存储

上传按 [01-requirements](01-requirements.md) FR-B1 的顺序校验（只收 PDF）；UUID 落盘（`uploads/{user_id}/{uuid}.pdf`）；不挂 StaticFiles；同用户同文件（sha256）去重。

### 4.20 配置

`pydantic-settings` 读 `.env`，阈值与常数集中在 `config.py`，仓库只提交 `.env.example`。
