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
④ 模拟面试（图 B）   技术面 → HR 面
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

三个子图各自可以单独 `invoke`：上传简历时只跑 parse；消融实验直接调 diagnose / match 子图。

### parse 子图

```
extract ──► layout ──┬─(有 unknown 页)─► llm_relayout ─┐
  PyMuPDF   分栏算法  └─(都判出来了)────────────────────┤
  python-docx                                          ▼
        section ──► structure ──► mentions ──► index_units
        章节识别    LLM 回 block_ids  词典扫技能   经历向量化 → Chroma resume_units
```

### diagnose 子图

```
rule_scan ──► dispatch ──Send×N──► review_unit ──► merge_findings ──► score
 7 条规则      成本预检              每条经历一个；节点内部：
 纯函数        mode 判断             LLM(json_mode) → locate_span 校验 → 失败带原因重试 ≤2
```

`mode ∈ {rule_only, llm_only, hybrid}`：图形状不变，只在 rule_scan / dispatch 内各一个 if。

### match 子图

```
dict_match ──► dispatch ──Send×M──► judge_requirement ──► recheck_missing ──► score_match
 词典精确命中   未命中的要求项         每条要求一个；节点内部：      判为 miss 的，         四维加权
 纯函数        分发                  ① resume_units 召回 top-10   用简历全文让 LLM       学历/年限为纯函数
                                    ② reranker 精排 top-3        复核一次（防检索漏掉）
                                    ③ LLM 判定 + 指出依据是哪条
                                    ④ 证据即该经历的 char 区间
```

`mode ∈ {dict_only, llm_fulltext, llm_rag, hybrid}`：

| mode | 行为 | 用途 |
|---|---|---|
| `dict_only` | dispatch 直接去 score_match，未命中即 miss | 基线 |
| `llm_fulltext` | 跳过 dict_match 与检索，judge 用简历全文，引用经 locate_span 校验 | 对照：不用 RAG |
| `llm_rag` | 跳过 dict_match，judge 走 召回→精排→判定 | 对照：只用 RAG |
| `hybrid`（默认） | 词典 → RAG 判定 → miss 复核 | 线上 |

**诚实的局限**：简历只有一两千字，全文塞给 LLM 完全放得下，RAG 在这里不是为了"装不下"，而是为了证据自带定位与可解释。检索可能漏掉相关经历，所以有 recheck_missing 兜底，并用四组实验给出数据结论——无论哪组赢都是可写的结论。

### 图 A 的 State

```python
class ApplyState(TypedDict):
    resume_id: int
    job_id: int
    need_parse: bool
    diagnose_mode: str
    match_mode: str
    full_text: str                       # 已做长度不变的 PII 掩码
    structure: dict
    requirements: list[dict]
    # 两个并行子图各写各的字段，reducer 保证并行写回不冲突
    rule_findings: Annotated[list, add]
    llm_findings: Annotated[list, add]
    rejected_findings: Annotated[list, add]
    match_items: Annotated[list, add]
    diagnose_score: dict | None
    match_score: dict | None
    passed: bool | None
    cost: Annotated[float, add]
```

## 6.3 图 B：模拟面试（走一步、等人、再走）

用 LangGraph `interrupt()` + `SqliteSaver`：图跑到 `wait_answer` 停住，状态存入检查点；用户提交回答后用 `Command(resume=answer)` 从原地继续。`thread_id = "interview:{session_id}"`。

```
                       START
                         │
                 ┌───────▼────────┐
                 │ plan_interview │  LLM 一次：话题列表，每个话题带来源
                 └───────┬────────┘  （诊断薄弱点 / JD 要求 / 简历项目）
             ┌───────────▼───────────┐
   ┌────────►│      pick_topic       │  纯函数：取本轮下一个话题
   │         └───────────┬───────────┘
   │                     ▼
   │         ┌───────────────────────┐  两个库各检索一次，各自 召回 → 精排 top-3
   │         │   retrieve_context    │  · resume_units   相关经历（该追问哪个项目）
   │         └───────────┬───────────┘  · interview_ctx  JD / 公司介绍 / 面经（这家怎么问）
   │                     ▼
   │         ┌───────────────────────┐
   │  ┌─────►│     ask_question      │  LLM 流式出题（temp 0.7）
   │  │      └───────────┬───────────┘
   │  │                  ▼
   │  │      ┌───────────────────────┐
   │  │      │     wait_answer       │  ★ interrupt()
   │  │      └───────────┬───────────┘
   │  │                  ▼
   │  │      ┌───────────────────────┐  LLM 按 rubric 打分（temp 0）
   │  │      │    evaluate_answer    │  必须逐字引用用户回答 → locate_span 校验
   │  │      └───────────┬───────────┘
   │  │                  ▼
   │  │      ┌───────────────────────┐
   │  │      │        decide         │  纯函数
   │  │      └───┬───────┬───────┬───┘
   │  │   追问   │       │ 换话题 │ 本轮结束 / 成本超限
   │  └──────────┘       │       ▼
   │  (depth+1，≤2)       │   ┌───────────────┐
   └─────────────────────┘   │ round_summary │  纯函数：算本轮分
                             └───────┬───────┘
                     还有 HR 面 ┌─────┴─────┐ 两轮都完
                               ▼           ▼
                        回 pick_topic   ┌──────────────┐
                        （换 HR persona）│ final_report │  分数纯函数聚合；LLM 只写文字总结
                                        └──────┬───────┘  verdict ∈ {pass, fail, practice}
                                              END
```

```python
class InterviewState(TypedDict):
    session_id: int
    mode: Literal["normal", "practice"]
    plan: list[dict]
    round: Literal["tech", "hr"]
    topic_idx: int
    depth: int                           # 0 主问，1/2 追问
    context: dict                        # 本话题检索到的片段
    turns: Annotated[list, add]          # {question, answer, evaluation}
    round_scores: dict
    cost: Annotated[float, add]
    cost_limit: float
```

**为什么这里用 LangGraph（此前的结论已更正）**：早先决定用 DB 状态机，是因为 LangGraph 的 Redis 检查点依赖 Redis Stack。但 `SqliteSaver` 是本地文件、零部署，该理由不成立；而 `interrupt()` 正是为"跑到一半停下来等人输入"设计的，比手写状态机更规范。已验证：全新进程用同一 thread_id 可从中断处恢复。

**两份状态的处理**：
- MySQL（`interview_sessions` / `interview_turns`）是面试记录的**权威来源**：报告、页面、评测全部读它。
- SQLite 检查点只负责让图能续跑。检查点损坏或丢失 → 从 MySQL 的 turns 重建 State，开新 thread。
- 检查点文件 `data/checkpoints.sqlite`，不进 git；会话结束后删除该 thread。

## 6.4 节点与技术对照

| 类型 | 节点 | 技术 |
|---|---|---|
| 纯函数（不调 API） | load_inputs · layout · section · mentions · rule_scan · dict_match · gate · build_gap_report · pick_topic · decide · round_summary · score · score_match | Python |
| LLM | llm_relayout · structure · review_unit · judge_requirement · recheck_missing · plan_interview · ask_question · evaluate_answer · final_report | DeepSeek，经 `llm/client.py`（缓存 · 限流 · 记账） |
| 检索 | index_units · judge_requirement 前半 · retrieve_context | bge-m3 → Chroma → bge-reranker（`retrieval/retriever.py`） |
| 证据校验 | review_unit / judge_requirement / evaluate_answer 内部 | `diagnose/evidence.locate_span`，三处同一个函数 |
| 等人 | wait_answer | `interrupt()` + `SqliteSaver` |

**DB 读写全部在图外**：service 层消费 `graph.stream()` 的事件，每步落库并发布 SSE 进度。节点只收发纯数据（不变量④）。

## 6.5 RAG 用在三处，同一条链路

```
匹配   JD 要求项   →检索→ resume_units                 → LLM 判定是否命中
改写   弱描述      →检索→ cases（优秀案例库）           → LLM 参考着改写
面试   面试话题    →检索→ resume_units + interview_ctx → 面试官出题
```

切块 → 向量化入库 → 召回（embedding）→ 精排（reranker）→ 注入 prompt。

## 6.6 必做线（任何时间点停下来都是一个完整的毕设）

```
第 1 层（M1–M4）  解析 + 诊断 + 原文高亮页面         到这里已是合格的毕设
第 2 层（M5）     JD 匹配 + 初筛 + 图 A               到这里是不错的毕设
第 3 层（M6–M7）  模拟面试（图 B）                    到这里是简历亮点
第 4 层           改写 RAG、各组对比实验               锦上添花
```

进度落后时的砍法（按顺序，每项互不影响）：RAG 检索消融实验 → 练习模式 → HR 面（只留技术面）→ DOCX 支持 → 改写模块。
