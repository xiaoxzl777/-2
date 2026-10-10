# 〇、概览

本科毕业设计（范围：AI 应用开发）。面向求职者的单端闭环：按目标岗位诊断简历、模拟初筛，再做模拟面试。
需求见 01-requirements，表结构见 02-database（12 张表），接口见 03-api（45 个，已实现 43 个）。

## 产品主线

```
选方向 → 定岗位（粘贴 JD 或选模板）→ 传简历 → 投递（诊断 ∥ 匹配 → 初筛）→ 模拟面试 → 报告
```

- 方向（计算机 / 运营 / 财会金融，别的专业选「其他」走通用包）存在岗位上，决定 JD 解析、诊断、匹配、建议、面试用哪套提示词和规则（领域包，04-design 4.16）。
- 初筛通过进正常模式面试；未通过看差距和具体建议，也可以用练习模式面试。面完出报告。
- 每次投递的结论和它下面的面试都在「我的投递」里回看，没面完的可以接着面；传过的简历在「我的简历」里管理，能看到每份投了哪些岗位。

完整流程与两张 LangGraph 图（图 A 投递、图 B 面试）见 06-workflows 6.1–6.3。

**三个技术内核**（对照实验见 05-evaluation-and-plan 5.2–5.3）：
1. 版面感知解析：region-first 启发式分栏 + 表格识别 + 时间轴规则（04-design 4.8）。
2. 规则 + LLM 可验证匹配：词典、学历、年限规则先判；判不了的要求连同简历全文一次交 LLM，引用的简历原文须经 `locate_span` 定位（04-design 4.12）。
3. 证据溯源校验：模型的结论必须能逐字定位回原文（`locate_span`，04-design 4.9）。用在诊断引用、匹配依据、JD 要求原话、结构化抽取的技能名、面试评分依据。
   具体建议另有一道数字复检：原文没有的数字换成【数值】（04-design 4.14）。

**应用层**：多轮自适应模拟面试（话题指向真实材料、追问有状态、评分有 rubric 有证据）。

## 系统不变量

```
① full_text 在解析完成后不再改变；所有 char 偏移都相对它，不提供会改动文本的功能。
② 每个块满足 full_text[char_start:char_end] == text（解析器单测断言）。
③ 解析（上传时触发，一次性）产出坐标系；诊断 / 匹配 / 面试只读坐标系，不改它。
④ 领域层（parser/ diagnose/ matching/ interview/ rewrite/ domains/ graphs/）不碰 DB、不直接 import langchain / httpx；
   模型调用都经 llm/ 包：对话用 client.py，向量 / 重排用 embedding.py（都过限流、记审计；
   管理端保存前的试连除外：services/provider_service.py 直接调，不限流、不记 llm_calls）。
⑤ PII：basics 本地抽取，不单独发给模型；外发的简历文本一律先做长度不变的掩码（匹配判定、差距建议发的是掩码后的全文，basics 那几行也在内）。
⑥ 模型的判断性输出必须附带可定位的原文引用。定位不到时：
   诊断 finding   带原因重试 ≤2 次，仍不行就丢弃（落库标 failed，不展示，评测统计拦截率用）
   匹配判定       该条按 miss 处理，依据作废
   面试评分       带原因重试 1 次，仍不行三项给中性 3 分、标 low_evidence，聚合时权重减半
```

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.13+ FastAPI + SQLAlchemy 2.0 + Pydantic v2 + pydantic-settings |
| 前端 | React 18 + TS + Vite + Tailwind v4（样式以手写 CSS 为主，集中在 `index.css`）+ Zustand + react-router；SSE 用 fetch 读流 |
| 对话模型 | 默认 DeepSeek `deepseek-chat`（LangChain `ChatDeepSeek`；管理端可换成别家，走 OpenAI 兼容接口，04-design 4.21）；结构化输出 = JSON 模式作答 + Pydantic 校验，解析失败不抛异常而是带原因重试；直连不走系统代理；面试问题用流式 |
| Embedding | 默认硅基流动 `BAAI/bge-m3`：检索第一阶段召回，只用在模拟面试里用户贴的长面经（匹配、建议都不检索，理由见 06-workflows 6.5） |
| Reranker | 默认硅基流动 `BAAI/bge-reranker-v2-m3`：检索第二阶段精排（召回 → 精排 top-3） |
| AI 编排 | LangGraph：图 A 投递流水线（diagnose ∥ match 两个子图并行 → 初筛；解析在图外，上传时触发）；图 B 模拟面试（`interrupt()` 等人输入 + `SqliteSaver` 检查点） |
| 存储 | MySQL 8.0 + Chroma 嵌入式 + Redis（缓存 / 限流 / SSE 推送）；图 B 的检查点是本地 SQLite 文件 `data/checkpoints.sqlite` |
| 异步 | FastAPI BackgroundTasks（解析、诊断、匹配），`uvicorn --workers 1`；面试逐轮为同步流式响应；很久没动静的面试启动时收尾一次、之后每小时一次 |
| 部署 | 本机 Docker Compose（`docker compose up -d --build`：Nginx 反向代理 + 前端静态文件、API、MySQL、Redis）；开发期本地跑 API / 前端 |

DeepSeek 不提供 embedding，向量默认走硅基流动。全部走 API，无本地模型。对话模型和检索模型都可以在管理端换（04-design 4.21）。
诊断与匹配的模式开关（`rule_only / llm_only / hybrid`、`dict_only / llm_fulltext / hybrid`）只为对照实验服务，见 05-evaluation-and-plan 5.3。
