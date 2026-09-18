> Exported from design plan v3 (2026-09-18). Source of truth: this docs/ folder; update docs before changing code.

# 智能求职辅助系统：简历诊断与模拟面试 — 需求分析与技术设计（v3）

> v2 → v3：用「模拟面试」替换 HR 批量筛选端，产品变为求职者单端闭环。表数仍 11 张，接口 24 个。
> v1 → v2：6 视角审查 + 双角色核验，采纳 26 项修订（矛盾抹平、约定定死、多余去掉）。

## Context

本科毕业设计（2026-09 启动，预计 2027-05 答辩），定位为**能撑起 AI 应用开发岗位面试的简历项目**。导师给定范围为「AI 应用开发」。

产品主线（求职者闭环）：

```
上传简历 ──► 解析 ──► 诊断（简历写得好不好）
                        │
                        ▼
              粘贴目标 JD ──► 匹配 = 模拟初筛
                        │
            ┌───────────┴───────────┐
         未通过                    通过（或练习模式）
            │                        │
     差距分析 + 改写建议         技术面 ──► HR 面 ──► 面试报告
     （改完重新上传再筛）              │
                                  报告薄弱点 ──► 改写建议
```

**三个技术内核**（每个都有对照实验，见第八章）：
1. 版面感知解析（region-first 启发式分栏）
2. 技能本体对齐（词典 → 本体祖先链 → embedding 三路）
3. 证据溯源校验（反幻觉：模型的每条结论必须能逐字定位回文本）——诊断 evidence、面试评分依据、改写占位符复检都是它的实例

**应用层亮点**：多轮自适应模拟面试（面试计划有出处、追问有状态、评分有 rubric 有证据、两个 persona）。

## 系统不变量

```
① full_text 在解析完成后永不改变。所有 char 偏移相对它；任何会改动文本的功能本期不提供。
② 每个块满足 full_text[char_start:char_end] == text（解析器单测断言）。
③ 解析任务（上传触发，一次性）产出坐标系；诊断 / 匹配 / 面试只消费坐标系，从不改它。
④ 领域层（parser/ diagnose/ matching/ interview/ graphs/）不碰 DB、不直接 import langchain / httpx；
   所有模型调用经 llm/client.py 唯一出口。
⑤ PII：basics 章节本地抽取，永不外发；其余外发文本经长度不变的掩码。
⑥ 模型的判断性输出（诊断 finding、面试评分）必须附带可定位的原文引用；定位失败即丢弃。
```

## 技术栈（已确认）

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+（开发机 3.13）+ FastAPI + SQLAlchemy 2.0 + Pydantic v2 + pydantic-settings |
| 前端 | React 18 + TS + Vite + Tailwind + shadcn/ui + Zustand + TanStack Query + @microsoft/fetch-event-source |
| 对话模型 | DeepSeek `deepseek-chat`（LangChain `ChatDeepSeek`）；结构化输出 `with_structured_output(method="json_mode", include_raw=True)`；面试问题用流式 |
| Embedding | 硅基流动 `BAAI/bge-m3` |
| Reranker | 硅基流动 `BAAI/bge-reranker-v2-m3`，只作用于 skills 召回 top-k，默认关 |
| AI 编排 | LangGraph（诊断工作流）；面试为跨 HTTP 请求的多轮状态机，状态存 DB（见 4.9） |
| 存储 | MySQL 8.0 + Chroma 嵌入式 + Redis（缓存 / 限流 / SSE 推送；checkpoint 本期不启用） |
| 异步 | FastAPI BackgroundTasks（解析、诊断、匹配），`uvicorn --workers 1`；面试逐轮为同步流式响应 |
| 部署 | Nginx 反向代理 + Docker Compose；开发期本地跑 API / 前端 |

> DeepSeek 不提供 embedding，向量走硅基流动。全部走 API，无本地模型。

### 开关 → 实验（第八章）

```
DiagnoseState.mode   rule_only / llm_only / hybrid        架构消融
use_reranker         False / True                          本体对齐阶梯第 ④ 步
use_rag              False / True                          改写 few-shot 对比
MODEL_REGISTRY       deepseek-chat / 硅基流动托管 Qwen      模型对比（可选）
```
