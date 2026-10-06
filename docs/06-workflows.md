# 六、产品流程与 LangGraph 工作流（设计 v4，2026-09-19）

> 本文件取代 04-design 中的 4.3（解析流水线）、4.4（诊断工作流）、4.9（面试状态机）三节的流程描述；
> 那三节里的 State 细节、prompt、算法仍然有效。

## 6.1 产品流程：JD 优先

用户的出发点是"我想去这家公司"，不是"我想分析简历"。界面顺序按真实求职漏斗排：

```
① 提交目标岗位      粘贴 JD（可附公司介绍、面经）；没有 JD 就选内置岗位模板
② 上传简历          已上传过的可直接选（同一份简历可投多个岗位，只解析一次）
        ↓ 点"投递"，后台自动跑图 A，用户看到进度条：解析中 → 诊断中 → 匹配中
③ 初筛结果
   ├ 通过   → "进入面试"
   └ 未通过 → 哪里不符合 = 对照 JD 的差距（匹配）+ 简历自身的问题（诊断）
              点某一条 → 原文高亮 + 改写建议
              → "去改简历重新投"  或  "以练习模式继续面试"
④ 模拟面试（图 B）   技术面（5 个话题，每个最多追问 1 次；HR 面不做）
⑤ 面试结果
   ├ 通过   → "恭喜通过" + 完整总结 + 改进建议
   ├ 未通过 → "很遗憾" + 同样完整的总结 + 改进建议 + 回到改简历
   └ 练习   → 不给通过结论，其余相同
```

三条设计决定：
- **诊断不单独占一个用户步骤**，在后台自动跑，结果融进"哪里不符合"和面试出题。用户看不到"诊断"这个词，但处处在用它。
- **初筛未通过不硬拦**：最需要练面试的正是简历弱的人；答辩演示也不能被一份没过线的简历卡住。
- **通过与未通过的总结同样完整**，差别只在开头一句和语气。

## 6.2 图 A：投递流水线（后台一次跑完）

输入 `resume_id + job_id`，输出初筛结果。由 `POST /apply` 触发，`graph.stream()` 每过一个节点吐一个事件 → 转成 SSE 进度。

```
                         START
                           │
                    ┌──────▼───────┐
                    │ load_inputs  │  读简历解析状态、读岗位要求项
                    └──────┬───────┘
          简历未解析 ┌──────┴──────┐ 已解析过
                    ▼             │
         ╔══════════════════╗     │
         ║   parse 子图      ║     │
         ╚════════╤═════════╝     │
                  └───────┬───────┘
                          │  并行分支，互不依赖
            ┌─────────────┴─────────────┐
            ▼                           ▼
  ╔══════════════════╗        ╔══════════════════╗
  ║  diagnose 子图    ║        ║   match 子图      ║
  ╚════════╤═════════╝        ╚════════╤═════════╝
            └─────────────┬─────────────┘   两条都完成才往下
                   ┌──────▼──────┐
                   │    gate     │  纯函数：overall_match ≥ SCREEN_THRESHOLD
                   └──────┬──────┘
               通过 ┌─────┴─────┐ 未通过
                    ▼           ▼
           ┌────────────┐  ┌─────────────────┐
           │ pass_result│  │ build_gap_report│  匹配差距 + 诊断 findings 合并排序
           └─────┬──────┘  └────────┬────────┘
                 └────────┬─────────┘
                         END
```

子图各自可以单独 `invoke`：消融实验（M8 的评测脚本）直接调 diagnose / match 子图。

> **实现说明（2026-09-19，与上图的两处差异）**
> - **解析不在图里**：上传时已经触发解析；`apply_service` 在跑图之前等它完成（解析要读文件、写数据库，不属于领域层）。
>   实际的图 A 是 `START → diagnose ∥ match → gate → END`（`graphs/apply_graph.py`）。
> - **"未通过说明"不在图里**：`pass_result / build_gap_report` 本质是对已落库结果的一种读法，
>   由 `GET /apply/{id}` 在读取时组装（gaps + resume_issues），这样每条问题都带数据库 id，前端可以直接点开改写。

### parse 子图

```
extract ──► layout ──► section ──► section_llm ──► structure ──► mentions
 PyMuPDF    分栏 / 表格  章节识别    认不出的标题     LLM 回 block_ids  词典扫技能
 找表格     / 时间轴                 交 LLM 归类（没有就跳过）
```

原设计在 layout 之后有一个 `llm_relayout` 分支（有 unknown 页就交 LLM 重排），2026-10-06 评估后不做：触发条件实测既漏报又误报，
最常见的错（时间轴被当成两栏）规则自报置信度 1.0，兜底根本触发不了，改用规则修。数据见 04-design 5.1 末尾。

### diagnose 子图

```
rule_scan ──► dispatch ──Send×N──► review_unit ──► merge_findings ──► score
 7 条规则      成本预检              每条经历一个；节点内部：
 纯函数        mode 判断             LLM(json_mode) → locate_span 校验 → 失败带原因重试 ≤2
```

`mode ∈ {rule_only, llm_only, hybrid}`：图形状不变，只在 rule_scan / dispatch 内各一个 if。

### match 子图

```
rule_match ──► judge_fulltext ──► score_match
 规则先判       规则判不了的要求，连同       公式加权算分
 （不花钱）     简历全文一次交给模型判断；
               模型的依据须逐字引用简历，经 locate_span 定位
```

`mode ∈ {dict_only, llm_fulltext, hybrid}`：

| mode | 行为 | 用途 |
|---|---|---|
| `dict_only` | 只用规则，判不了的直接记 miss，不调模型 | 基线 |
| `llm_fulltext` | 跳过规则，全部要求交给模型 | 对照：只用模型 |
| `hybrid`（默认） | 规则只判十拿九稳的（要求就是技能名本身、且经历里确实用过；学历；年限），其余交给模型 | 线上 |

**为什么匹配不用 RAG（2026-09-19 调整）**：简历只有一两千字，全文放进 prompt 毫无压力，不存在"资料太多"的问题。
最初的设计是逐条要求 `召回 → 精排 → 判定`，并对判为 miss 的再用全文复核一次。用真实简历 × 校招 JD 实测（单份样本，仅作设计依据）：

| 做法 | 模型调用 | 耗时 | 花费 | 现象 |
|---|---|---|---|---|
| 全文一次判断 | 1 次 | 3.7 s | ¥0.018 | — |
| 逐条 RAG 判断 | 18 次 + 36 次向量 / 重排 | 5.1 s | ¥0.028 | 检索单元没覆盖到的内容（学历、技术栈行）会被误判为 miss，需要全文复核来兜底 |

RAG 更贵、更慢、还多一种出错方式，于是从匹配中移除。检索层（`llm/embedding.py`、`retrieval/unit_store.py`）保留，
用在真正资料多的地方：模拟面试里作为面试官的**检索工具**，查用户贴的面经 / 公司介绍 / JD（见 6.5）。

### 图 A 的 State

（与 `graphs/apply_graph.py` 一致）

```python
class ApplyState(TypedDict, total=False):
    # ── 输入 ──
    diagnosis_id: int | None
    match_report_id: int | None
    diagnose_mode: str
    match_mode: str
    model: str | None
    job_title: str | None
    requirements: list[dict]
    structure: dict
    full_text: str                       # 原文，用来切证据
    masked_text: str                     # 长度不变的 PII 掩码，外发给模型的是它
    ats_signals: dict
    page_count: int | None
    # ── 输出 ──
    diagnosis: dict                      # 诊断子图的完整输出
    match: dict                          # 匹配子图的完整输出
    passed: bool
```

两个子图的 State 与图 A 不同，所以各用一个普通节点包一层（取输入 → invoke 子图 → 整个输出放进一个字段）。
两个分支写的是不同字段，不需要 reducer。

## 6.3 图 B：模拟面试（走一步、等人、再走）

**只做技术面**（2026-09-27 定：HR 面太主观，不做）。一场 5 个话题，每个最多追问 1 次，约 5–10 问；题数是配置项（`INTERVIEW_TOPICS` / `INTERVIEW_MAX_FOLLOWUP`）。

用 LangGraph `interrupt()` + `SqliteSaver`：图跑到 `wait_answer` 停住，状态存入检查点；用户提交回答后用 `Command(resume={text, skip})` 从原地继续。`thread_id = "interview:{session_id}"`。

```
   创建会话（POST /interviews）只跑到这里 ─┐
                                          ▼
 START ─► plan_interview ─► pick_topic ─┬─► retrieve_context ─► ask_question ─► wait_answer ─► evaluate_answer ─► decide
          LLM 一次：5 个话题，    纯函数  │   方案 C：只查面经      LLM 流式     ★ interrupt()   LLM 按 rubric 打分，   纯函数
          每个指向一条材料                │  （不长就整段给）      temp 0.7                     依据逐字引用回答
                          ▲              │                            ▲                                            │
                          │              └─(话题用完)─► final_report ─► END                                         │
                          │                                  ▲    分数纯函数聚合；LLM 只写文字总结                     │
                          └──────────── next ────────────────┼─────────── finish（成本到顶）────────────────────────────┤
                                                ask_question ◄────────── followup（depth + 1，最多 1 次）──────────────┘
```

- **创建时只定话题**：`graph.invoke(state, config, interrupt_before=["pick_topic"])` 跑完 plan_interview 就停；之后 `POST /start` 用 `graph.stream(None, config)` 接着跑。整个流程都在一张图里。
- **话题来源**：简历项目 / 工作经历（P1、P2…）、岗位要求（R + 要求 id，学历和软素质不进面试）、初筛发现的简历问题（F + 问题 id）。模型照抄编号，代码核对，指向不存在的丢掉。
- **问到哪个话题才显示哪个**：接口和页面都不提前列出话题（用户看 demo 时提的）。
- **评价按模式区分**：练习模式（初筛没过，或主动选）每题答完马上给点评；正常模式答题时不给，结束后看报告。两种模式后台都逐题评分（追问要用）。跳过的题两种模式都不给任何反馈，直接出下一题。
- **结论**：练习模式不下结论；没聊完所有话题就结束（用户提前结束、成本到顶）也不下结论（incomplete）；其余综合分 ≥ 60 通过。
- 提前结束（`POST /finish`）不经过图：按 MySQL 里已评完分的题直接出报告。

```python
class InterviewState(TypedDict):
    session_id: int
    mode: Literal["normal", "practice"]
    materials: dict                      # 岗位要求 + 初筛判定、经历（掩码文本）、简历问题、面经
    topic_count: int; max_followup: int; cost_limit: float; threshold: float
    plan: list[dict]                     # [{idx, source, ref, label, intent}]
    topic_idx: int                       # -1 = 还没开始
    depth: int                           # 0 主问题，1 追问
    context: list[str]                   # 当前话题的面经片段
    question: str; answer: str; skipped: bool; evaluation: dict; next_step: str
    history: Annotated[list, add]        # {topic_idx, depth, question, answer, skipped, evaluation}
    cost: Annotated[float, add]
    report: dict
```

**为什么这里用 LangGraph（此前的结论已更正）**：早先决定用 DB 状态机，是因为 LangGraph 的 Redis 检查点依赖 Redis Stack。但 `SqliteSaver` 是本地文件、零部署，该理由不成立；而 `interrupt()` 正是为"跑到一半停下来等人输入"设计的，比手写状态机更规范。已验证：全新进程用同一 thread_id 可从中断处恢复。

**两份状态的处理**：
- MySQL（`interview_sessions` / `interview_turns`）是面试记录的**权威来源**：报告、页面、评测全部读它。话题计划和材料也存在 `sessions.plan` 里。
- SQLite 检查点只负责让图能续跑。检查点丢失 → 用 MySQL 里的材料、话题、问答拼回 State，`update_state(as_node=…)` 停回该停的那一步。
- 任何一步失败，检查点都停在失败的那个节点之前，`POST /start` 从那里重跑。回答先落库再恢复图，评分失败也不丢回答。
- 检查点文件 `data/checkpoints.sqlite`，不进 git；会话结束后删除该 thread 和面经切段。24 小时没动静的会话在启动清理时按已答的题出报告、标成 abandoned。

## 6.4 节点与技术对照

| 类型 | 节点 | 技术 |
|---|---|---|
| 纯函数（不调 API） | load_inputs · layout · section · mentions · rule_scan · rule_match · gate · pick_topic · decide · score · score_match | Python |
| LLM | section_llm · structure · review_unit · judge_fulltext · plan_interview · ask_question · evaluate_answer · final_report | DeepSeek，经 `llm/client.py`（缓存 · 限流 · 记账） |
| 检索 | 面试的 retrieve_context：只在用户贴的面经超过 3000 字时检索 | bge-m3 → Chroma → bge-reranker（`retrieval/context_store.py`） |
| 证据校验 | review_unit / judge_fulltext / evaluate_answer 内部，以及 JD 解析 | `diagnose/evidence.locate_span`，三处同一个函数 |
| 等人 | wait_answer | `interrupt()` + `SqliteSaver` |

**DB 读写全部在图外**：service 层消费 `graph.stream()` 的事件，每步落库并发布 SSE 进度。节点只收发纯数据（不变量④）。

## 6.5 RAG 的位置：面试里的一个工具

RAG 解决的是"资料太多、塞不进 prompt"。按这个标准逐处检查：

```
匹配   简历 + JD 一共两三千字            → 不需要检索，全文直接给模型（见 6.2）
改写   暂无范例库                        → 先不做检索：模型改写 + 数字占位符复检；以后有了范例库再接
面试   简历、JD 同样很短，每个话题又本来就指向    → 简历、JD 不检索，整段给
       具体的某段经历 / 某条要求
       用户贴的面经 / 公司介绍可能上万字           → 只有这部分检索（方案 C，2026-09-27 定）：不超过 3000 字整段给面试官，
                                                    更长才切段，每个话题取最相关的 3 段；没贴就跳过
```

链路不变：切块 → 向量化入库（bge-m3）→ 召回 → 精排（bge-reranker）→ 注入 prompt。语料来自用户自己贴的材料，不需要另外收集数据。
检索是图 B 里固定的一个节点（retrieve_context），不做"让模型自己决定查不查"的工具调用：流程固定、好测，也方便做有检索 / 没检索的对比。

## 6.6 必做线（任何时间点停下来都是一个完整的毕设）

```
第 1 层（M1–M4）  解析 + 诊断 + 原文高亮页面         到这里已是合格的毕设
第 2 层（M5）     JD 匹配 + 初筛 + 图 A               到这里是不错的毕设
第 3 层（M6–M7）  模拟面试（图 B）                    到这里是简历亮点
第 4 层           改写 RAG、各组对比实验               锦上添花
```

进度落后时的砍法（按顺序，每项互不影响）：RAG 检索消融实验 → 练习模式 → DOCX 支持 → 改写模块。（HR 面已经决定不做。）
