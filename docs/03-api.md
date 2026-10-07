# 三、接口设计

统一前缀 `/api/v1`；所有接口（含 SSE）用 `Authorization: Bearer <token>`，SSE 前端用 fetch 读流（EventSource 带不了请求头，也发不了 POST），见 `frontend/src/api/client.ts`。
统一响应 `{ "code": 0, "message": "success", "data": {} }`。

## 3.1 错误码

| code | 含义 | HTTP |
|---|---|---|
| 0 | 成功 | 200 |
| 40001 | 参数校验失败 | 400 |
| 40101 | 未认证 / token 失效 | 401 |
| 40401 | 资源不存在（含越权） | 404 |
| 40901 | 状态冲突：解析未完成 / 已有诊断进行中 / 面试已结束或未开始 / 缺少匹配报告 | 409 |
| 41301 | 文件超出大小限制 | 413 |
| 41501 | 不支持的文件（类型 / 加密 / 解压异常） | 415 |
| 42201 | 文件篇幅超限 | 422 |
| 42901 | 请求过于频繁 | 429 |
| 50001 | 服务器内部错误 | 500 |
| 50002 | LLM 调用失败 | 500 |
| 50003 | 简历解析失败（含扫描件） | 500 |

## 3.2 接口清单（30 个；已实现 28 个，标〔未实现〕的留给后续里程碑）

另有 `GET /api/v1/health`（启动自检：MySQL / Redis 是否可用），不计入 30 个。

```
认证 3    POST /auth/register   POST /auth/login   GET /auth/me

简历 7    POST   /resumes                  → {id, task_id:"parse:{id}"}
          GET    /resumes                  GET /resumes/{id}                DELETE /resumes/{id}
          GET    /resumes/{id}/blocks      GET /resumes/{id}/structure      PATCH /resumes/{id}/structure〔未实现〕

诊断 1    GET  /resumes/{id}/diagnosis     ?diagnosis_id=      诊断由投递触发，这里只查结果

进度 1    GET  /tasks/{kind}/{id}/stream   SSE；kind ∈ {parse, apply}

投递 3    POST /apply  {resume_id, job_id, diagnose_mode?, match_mode?, model?} → {id, diagnosis_id, task_id:"apply:{id}", status}   图 A
                       投递 id = match_report_id；简历还在解析也可以投，后台任务先等解析完成
          GET  /apply/{id}  → status / stage / gate{passed, overall_match, threshold} / dimension_scores / resume_score
                       + gaps[]（未满足与部分满足的要求，重要的在前）+ resume_issues[]（诊断里最严重的 8 条，带 finding id）
                       + interviews[]（这次投递下面的面试，新的在前；字段同下面 GET /apply 的 interviews）
          GET  /apply  ?page=&page_size=（≤100）「我的投递」，新的在前；简历删了的不列
                       → Page[{id, status, overall_match, passed, failure, job_id, job_title, company, domain, resume_id,
                               resume_title, created_at, interviews[{id, mode, status, topic_count, current_topic, overall, verdict}]}]
                       failure 是给用户看的一句话（不是 error_msg）；interviews 是这次投递下面的面试，新的在前

方向 1    GET  /domains    不用登录 → [{key, name, icon, desc, rule_hint, interview_hint, interview_label, interviewer, sample_jd}]
                       工作台第一步「选方向」的下拉框；顺序即下拉顺序（app/domains，目前 cs 计算机 / ops 运营）

岗位 4    POST /jobs   {title, company?, raw_text, domain?}  同步解析（一次模型调用，约 2–4 秒）→ 岗位 + requirements[]
                                                           domain 默认 cs，未知方向 40001；按方向取 JD 解析的提示词
                                                           每条要求带 JD 原文引用 quote 与 char 区间；定位不到的丢弃；失败则不保存
          GET  /jobs   ?include_templates=1（每条带 domain） GET /jobs/{id}        DELETE /jobs/{id}（软删除；模板不可删）

匹配 1    GET  /match/{id}     匹配由投递触发，这里只查报告（id = 投递 id）
                       → status / overall_match / passed / threshold / dimension_scores / items[]
                       items[] 每条 = 要求项内容 + status(hit|partial|miss) + matched_by(dict|profile|fulltext)
                       + reason + 简历原文依据 evidence_quote 与 char 区间

建议 2    POST /findings/{id}/advice                          简历里的一条问题：【问题】【改成】【为什么】
          POST /match/{id}/items/{requirement_id}/advice      岗位里没满足 / 部分满足的一条要求：【考察什么】【怎么补】【面试怎么答】
                       结果页点开一条时现场生成，流式返回（POST + text/event-stream，见 3.3）；生成过的存库，再请求直接回一个 done
                       分别存进 findings.rewrite 与 match_reports.items[k].advice，GET /apply/{id} 与 GET /match/{id} 会带回来
                       本期不做检索：模型针对原句写建议 + 数字占位符复检（06-workflows 6.5；提示词见 llm/prompts.py 的 ADVICE_*）

面试 6    只有技术面：5 个话题，每个最多追问 1 次（docs/06-workflows 6.3）
          POST /interviews                 {apply_id, company_name?, extra_context?, practice?}
                                           → {id, mode, gate:{passed, overall_match, threshold}, topic_count, context_mode}
                                           初筛没过的一律是练习模式（practice）；过了的也可以主动选练习模式
          POST /interviews/{id}/start      → SSE：开始 / 继续（中途失败了也用它从原处继续；正在等回答就把那道题再发一次）
          POST /interviews/{id}/answer     {text, skip?} → SSE：evaluation（仅练习模式）→ 下一题 | finished
          POST /interviews/{id}/finish     提前结束：按已评完分的题出报告 → 同 GET /report
          GET  /interviews/{id}            会话 + 已问到的话题 + turns（正常模式在结束前不给评分）
          GET  /interviews/{id}/report     报告 + 逐题回顾（结束前 40901）

系统 1    GET /system/info〔未实现〕       模型列表 + 规则清单 + 用量（用量需 admin）
```

## 3.3 异步任务与 SSE 契约

```
后台任务   task_id="{kind}:{id}"，kind ∈ {parse, apply}；apply 的 stage ∈ parsing/analyzing/diagnose/match/gate（diagnose 与 match 并行，先完成的先到）；Redis pub/sub channel task:{kind}:{id}
           event: progress {"stage","percent","message"} / done {"kind","id","status"} / error {"code","message"}
           progress 来自 Redis 频道（只有 apply 会发）；done {"kind","id","status"} / error 以数据库里的任务状态为准，
           SSE 接口每秒顺带查一次——连上来时任务已结束、或中途漏了消息，都一定能收到结束事件；15s 无事件发一行 ": keep-alive"
           兜底：SSE 连不上或 30s 无事件 → 每 3s 轮询对应资源 status（apply 轮询 GET /apply/{id} 的 stage）
具体建议   同步流式响应（POST + text/event-stream），不经 pub/sub：
           event: delta {"text":"..."}  ×N                                 ← 边生成边显示
           event: done  {"text","violation_count","prompt_version","model","created_at"}   ← 数字复检后的全文，以它为准整段替换
           event: error {"code","message"}                                 ← 什么都不存，前端可以重试
面试逐轮   同步流式响应（POST + text/event-stream），不经 pub/sub：
           event: evaluation {"turn_id","score","scores","evidence","good","bad","better_answer","decision",…}  ← 上一题的点评，只有练习模式发；跳过的题不发
           event: topic      {"idx","label","source","count"}                ← 问到一个新话题（前端这时才显示它）
           event: asking     {"topic_idx","depth"}                           ← 开始出题，depth > 0 是追问
           event: question   {"delta":"..."}  ×N                              ← 题目逐段
           event: asked      {"turn_id","text","topic_idx","depth"}          ← 题目出完，等回答
           event: finished   {"report_ready","verdict","overall"}
           event: error      {"code","message"}                              ← 之后调 POST /start 从原处继续
Nginx      proxy_buffering off; proxy_cache off; proxy_http_version 1.1; proxy_set_header Connection '';
           proxy_read_timeout 900s; gzip 不含 text/event-stream；FastAPI 响应带 X-Accel-Buffering: no（三处流式接口共用 api/sse.py）
```

## 3.4 关键接口示例

**POST /interviews**（要几秒：面经太长时先切段向量化，然后一次模型调用定下话题）

```json
{ "code": 0, "data": {
    "id": 17, "mode": "normal",
    "gate": { "passed": true, "overall_match": 76.7, "threshold": 60 },
    "topic_count": 5,
    "context_mode": "full"
} }
```

只给话题个数，不给话题内容：问到哪个话题才显示哪个（GET /interviews/{id} 的 topics 也只列问到了的）。
`context_mode`：none = 没贴面经；full = 面经不超过 3000 字，整段给面试官；retrieval = 更长，切段后按话题检索。

**POST /interviews/{id}/answer** → SSE（练习模式）

```
event: evaluation
data: {"turn_id":203,"skipped":false,"score":67,"scores":{"correctness":4,"depth":2,"clarity":4},
       "evidence":[{"quote":"先更新数据库再删缓存"}],"good":"说出了先更新库再删缓存的常见做法",
       "bad":"没说为什么这么选，也没提并发下的问题","better_answer":"……【接口耗时从多少降到多少】……",
       "decision":"followup","low_evidence":false}

event: asking
data: {"topic_idx":0,"depth":1}

event: question
data: {"delta":"你刚说先更新数据库再删缓存，"}
event: question
data: {"delta":"删失败了怎么办？"}

event: asked
data: {"turn_id":204,"text":"你刚说先更新数据库再删缓存，删失败了怎么办？","topic_idx":0,"depth":1}
```

正常模式没有 evaluation 事件；换到新话题时在 asking 之前多一个 `topic`。话题用完：`evaluation`（练习模式）→ `finished`。

**GET /interviews/{id}/report**

```json
{ "code": 0, "data": {
    "id": 17, "apply_id": 8, "mode": "normal", "status": "completed", "topic_count": 5,
    "topics": [ … ], "turns": [ { "id": 203, "topic_idx": 0, "depth": 0, "question": "…", "answer": "…", "evaluation": { … } } ],
    "report": {
      "overall": 71, "verdict": "pass", "threshold": 60, "early": false, "answered": 8, "summary_ok": true,
      "topics": [ { "idx": 0, "label": "二手交易平台 · 缓存", "source": "project", "score": 73 },
                  { "idx": 2, "label": "消息队列", "source": "requirement", "score": 47 } ],
      "strengths":  [ { "title": "定位问题有方法", "detail": "慢查询那题：用 EXPLAIN 找到全表扫描……" } ],
      "weaknesses": [ { "title": "说不出成果数据", "detail": "订单模块两次被问到效果……" } ],
      "links": [ { "kind": "requirement", "ref_id": 9, "topic_idx": 2, "label": "了解消息队列", "text": "先补……" } ]
    }
} }
```

`verdict`：pass / fail / practice（练习模式不下结论）/ incomplete（没聊完所有话题就结束，不下结论）。`links` 只挑得分低于 60、来源是简历问题或岗位要求的话题，前端点过去是结果页上对应的那一条。

**GET /resumes/{id}/diagnosis**：诊断状态、mode、overall_score、五维 score_detail、统计（stats）、花费，以及 findings[]（来源、规则码 / 风险类型、严重度、证据原文与 char 区间、verify_result、rewrite）；字段以 `schemas.py` 的 `DiagnosisOut` 为准。
