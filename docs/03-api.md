# 三、接口设计

统一前缀 `/api/v1`。除了 `POST /auth/register`、`POST /auth/login`、`GET /domains`、`GET /health`、`GET /system/llm`，其余接口都要登录：请求头带 `Authorization: Bearer <token>`（JWT，有效期 `JWT_EXPIRE_HOURS`，默认 24 小时）。流式接口也带这个头，所以前端用 fetch 读流，不用 EventSource（它带不了请求头，也发不了 POST），见 `frontend/src/api/client.ts`。

统一响应 `{ "code": 0, "message": "success", "data": {...} }`。出错时 `data` 为 null，`message` 是给用户看的中文说明，HTTP 状态码取 code 的前三位（`GET /health` 例外，见 3.2）。

本章只写契约语义：路径、鉴权、取值含义、什么情况报什么错、SSE 事件、分页。**响应的具体字段以 `backend/app/schemas.py` 里对应的 `XxxOut` 为准**，示例里只列要点。

分页：列表接口收 `?page=`（从 1 起）`&page_size=`（默认 20，最大 100），返回 `{items, total, page, page_size}`（`schemas.Page`）。目前分页的是 `GET /resumes` 和 `GET /apply`；`GET /jobs` 一次全给。

## 3.1 错误码

| code | 含义 | 什么时候抛 | HTTP |
|---|---|---|---|
| 0 | 成功 | | 200 |
| 40001 | 参数错误 | 请求体或查询参数校验不过；未知的求职方向、模型、任务类型；面试回答为空或超过 `INTERVIEW_ANSWER_MAX`（3000 字）；JD 里识别不出任何要求 | 400 |
| 40101 | 未认证 | 没带令牌、令牌失效或过期；登录时用户名或密码错误（不区分是哪个错） | 401 |
| 40401 | 资源不存在 | 不存在、不属于当前用户、已软删除的一律按不存在处理，不暴露是否存在；包括简历、岗位（含删除内置模板）、投递 / 匹配报告、诊断记录、问题条目、没满足的要求、面试、任务 | 404 |
| 40901 | 状态冲突 | 注册时用户名或邮箱已被占用；简历还在解析时读它的块 / 结构；投递时同一份简历已有诊断在跑，或同一份简历对同一岗位的匹配在跑；初筛还没完成（或失败了）就建面试；面试已经结束还要继续 / 提前结束，还没开始或已结束时提交回答，还没出题，这道题已经答过，上一步还在进行；面试还没结束就取报告 | 409 |
| 41301 | 文件太大 | 超过 `MAX_UPLOAD_MB`（20MB） | 413 |
| 41501 | 不支持的文件 | 扩展名不是 .pdf；文件头不是 PDF；打不开（文件损坏）；PDF 加密 | 415 |
| 42201 | 篇幅超限 | 页数超过 `MAX_PDF_PAGES`（10 页） | 422 |
| 42901 | 〔未使用〕请求过于频繁 | 只在 `errors.py` 里定义，没有地方抛。限流管的是调模型，不是接口请求：每次调模型（对话、向量、重排）前，在 Redis 里按服务商、按分钟占一个名额（`DEEPSEEK_RPM` / `SILICONFLOW_RPM`，各 300），满了就等到下一分钟；最多等 120 秒，超时或 Redis 不通都按模型调用失败处理，同步接口返回 50002，后台任务按各自的失败或降级逻辑处理 | 429 |
| 50001 | 服务器内部错误 | 没接住的异常 | 500 |
| 50002 | 模型调用失败 | 同步调模型的接口失败：JD 解析、建面试时定话题；具体建议、面试流里的 error 事件也用这个 code。模型服务调不通（余额不足、密钥无效、连不上、服务端 429 / 5xx）时 message 是「模型服务暂时不可用……」，其余失败是「……请稍后重试」 | 500 |
| 50003 | 简历解析失败 | 简历解析已经失败，还去读它的块 / 结构，或拿它投递；message 按失败原因给（扫描件、加密、模型失败、服务重启打断等） | 500 |

后台任务（解析、投递分析）里的失败不走错误码，落成记录的 failed 状态，通过 SSE 的 error 事件或轮询状态告诉前端（3.3）。

## 3.2 接口清单（30 个；已实现 28 个，标〔未实现〕的留给后续里程碑）

另有 `GET /api/v1/health`，不计入 30 个，不用登录。它是运行时探针：逐项探测 MySQL、Redis，返回 `{mysql, redis, version}`，每项为 `ok` 或 `error: <异常类型>`；任一依赖异常时 code 为 50001、HTTP 503。部署出问题时先看它。启动时的检查是另一回事：在 `main.py` 的 lifespan 里，连不上 MySQL、缺表、连不上 Redis 都直接报错退出。

还有 `GET /api/v1/system/llm`，也不计入 30 个、不用登录：模型服务现在能不能用，返回 `{available}`，登录后页面顶上的横幅按它显示。后端问 DeepSeek 的余额接口（不花钱），结论在 Redis 里存 1 分钟（04-design 4.6）。故意不放进 `/health`：余额用完不该让容器被判成不健康，网站别的部分照常能用。

```
认证 3    POST /auth/register  {username, password, email?}  → 令牌 + 用户（注册成功直接登录）；不用登录
          POST /auth/login     {username, password}          → {access_token, token_type, expires_in, user}；不用登录
          GET  /auth/me        当前用户（前端刷新页面时用它恢复登录态）

简历 7    POST   /resumes      multipart：file（PDF，≤20MB，≤10 页）+ title?
                               → {id, task_id:"parse:{id}", parse_status, deduplicated}；立即返回，解析在后台跑
                               去重：同一用户、未删除的简历里有同一文件（SHA-256 相同）就复用那条记录，deduplicated = true；
                               复用时只有上次解析失败的才重新解析，pending / parsing 的说明已有任务在跑，success 的直接用旧结果
          GET    /resumes                  ?page=&page_size=，最近更新的在前；每条带 apply_count（用它投过几次，删除前提示用）
          GET    /resumes/{id}             DELETE /resumes/{id}（软删除；用它的投递、面试报告在「我的投递」里一起隐藏）
          GET    /resumes/{id}/blocks      full_text + 按阅读顺序的 blocks[] + sections[] + 版面判定；前端渲染原文、按 char 区间高亮
          GET    /resumes/{id}/structure   结构化结果（02 2.3）
                               blocks / structure：还在解析 40901，解析失败 50003
          PATCH  /resumes/{id}/structure〔未实现〕

诊断 1    GET  /resumes/{id}/diagnosis     ?diagnosis_id=      诊断由投递触发，这里只查结果
                               不带 diagnosis_id：最近一次已完成的诊断，没有就给最近一次（可能还在跑）；一次都没有 40401
                               findings[] 只含证据校验通过的（verify_result ≠ failed）

进度 1    GET  /tasks/{kind}/{id}/stream   SSE；kind ∈ {parse, apply}，事件见 3.3

投递 3    POST /apply  {resume_id, job_id, diagnose_mode?, match_mode?, model?} → {id, diagnosis_id, task_id:"apply:{id}", status}   图 A
                       投递 id = match_report_id；简历还在解析也可以投，后台任务先等解析完成（最多 120 秒）；解析已失败的 50003
                       diagnose_mode / match_mode / model 是评测用的开关，页面不传（默认 hybrid、默认模型）
          GET  /apply/{id}  → status / stage / gate{passed, overall_match, threshold}（跑完才有）/ dimension_scores / resume_score
                       + gaps[]（未满足与部分满足的要求，重要的在前）+ resume_issues[]（诊断里最严重的 8 条，带 finding id）
                       + interviews[]（这次投递下面的面试，新的在前，字段同 GET /apply）
                       stage ∈ parsing（简历还在解析）/ queued（解析好了、分析还没开始）/ analyzing / done / failed，
                       由 status 推出来（apply_service.stage_of），比 SSE 进度事件的 stage 粗，是轮询兜底用的
          GET  /apply  ?page=&page_size=  「我的投递」，新的在前；简历删了的不列
                       → Page[{id, status, overall_match, passed, failure, job_id, job_title, company, domain, resume_id,
                               resume_title, created_at, interviews[]}]
                       passed 只在 status = success 时有值；failure 是失败时给用户看的一句话（不是 error_msg）
                       interviews[] 每项 {id, mode, status, topic_count, current_topic, overall, verdict, created_at}
                       （schemas.ApplyInterviewBrief）：current_topic 进行中时从 1 起，其他状态为 0；overall / verdict 结束后才有

方向 1    GET  /domains    不用登录 → [{key, name, icon, desc, rule_hint, interview_hint, interview_label, interviewer, sample_jd, note}]
                       工作台第一步「选方向」的下拉框；顺序即下拉顺序（app/domains，目前 cs 计算机 / ops 运营 / finance 财会金融 / general 其他）；
                       note 只有 general 有（「结果可能不够准」，页面上照原文显示），其余为空
                       interview_label / interviewer 是页面上对面试的称呼（技术面 / 运营面、技术面试官 / 运营面试官）

岗位 4    POST /jobs   {title, company?, raw_text, domain?}  同步解析（一次模型调用，约 2–4 秒）→ 岗位 + requirements[]
                                                           raw_text 30–10000 字；domain 默认 cs，未知方向 40001
                                                           每条要求带 JD 原文引用 quote 与 char 区间，定位不到的丢弃；
                                                           模型失败 50002、一条要求都没识别出 40001，这两种都不保存
          GET  /jobs   ?include_templates=1   自己的岗位（新的在前），带上时内置模板排在后面；每条带 domain
          GET  /jobs/{id}（自己的或模板）     DELETE /jobs/{id}（软删除；模板不能删，返回 40401）

匹配 1    GET  /match/{id}     匹配由投递触发，这里只查报告（id = 投递 id）
                       → status / overall_match / passed / threshold / dimension_scores / items[]
                       items[] 每条 = 要求项内容 + status(hit|partial|miss) + matched_by(dict|profile|fulltext|null)
                       + reason + 简历原文依据 evidence_quote 与 char 区间

建议 2    POST /findings/{id}/advice                          简历里的一条问题：【问题】【改成】【为什么】
          POST /match/{id}/items/{requirement_id}/advice      岗位里没满足 / 部分满足的一条要求：【考察什么】【怎么补】【面试怎么答】
                       结果页点开一条时现场生成，流式返回（POST + text/event-stream，见 3.3）；生成过的存库，再请求直接回一个 done
                       分别存进 findings.rewrite 与 match_reports.items[k].advice，GET /apply/{id} 与 GET /match/{id} 会带回来
                       已满足的要求、证据校验没通过的问题都按不存在处理（40401）
                       本期不做检索：模型针对原句写建议 + 数字占位符复检（06-workflows 6.5；提示词见 llm/prompts.py 的 ADVICE_*）

面试 6    一轮专业面（计算机方向叫技术面、运营方向叫运营面），库里 round 恒为 tech；
          默认 5 个话题（INTERVIEW_TOPICS），每个最多追问 1 次（docs/06-workflows 6.3）
          POST /interviews                 {apply_id, company_name?, extra_context?, practice?}
                                           → {id, mode, gate:{passed, overall_match, threshold}, topic_count, context_mode}
                                           初筛没过的一律是练习模式（practice）；过了的也可以主动选练习模式
                                           初筛还没完成或失败了 40901；定话题失败 50002
          POST /interviews/{id}/start      → SSE：开始 / 继续（中途失败了也用它从原处继续；正在等回答就把那道题再发一次）
          POST /interviews/{id}/answer     {text, skip?} → SSE：evaluation（仅练习模式）→ 下一题 | finished
                                           跳过时 answer 存空串；回答先落库再推进，评分失败回答也不丢
          POST /interviews/{id}/finish     提前结束：按已评完分的题出报告 → 同 GET /report
          GET  /interviews/{id}            会话 + 已问到的话题 + turns + waiting（最后一题出了还没答）+ report_ready
                                           正常模式在结束前不给评分；页面刷新后靠它恢复
          GET  /interviews/{id}/report     报告 + 逐题回顾（结束前 40901）
          24 小时（INTERVIEW_IDLE_HOURS）没动静的面试，服务启动时、之后每小时收尾一次：按已答的题出报告、标成 abandoned

系统 1    GET /system/info〔未实现〕       模型列表 + 规则清单 + 用量（用量需 admin）
```

## 3.3 异步任务与 SSE 契约

三处流式接口共用 `api/sse.py`：响应头 `Content-Type: text/event-stream`、`Cache-Control: no-cache`、`X-Accel-Buffering: no`；每个事件是 `event: <名字>` 加一行 `data: <JSON>`。

```
后台任务   GET /tasks/{kind}/{id}/stream；task_id = "{kind}:{id}"，kind ∈ {parse, apply}（apply 的 id 就是投递 id）
           未知 kind 40001；不是自己的、不存在的 40401
           event: progress {"stage","percent","message"}     来自 Redis 频道 task:{kind}:{id}，原样转发；目前只有 apply 会发
                  stage：parsing(5) → analyzing(20) → diagnose(60) / match(85)（并行，先完成的先到）→ gate(95)
           event: done  {"kind","id","status"}                任务成功结束，status = success
           event: error {"kind","id","status"}                status = failed（任务失败）/ null（记录不存在了）/
                                                              timeout（流开满 600 秒任务还没结束，任务可能还在跑，改用轮询）
           done / error 以数据库里的任务状态为准：接口每秒查一次库，连上来时任务已经结束、或中途漏了频道消息，都一定能收到结束事件
           15 秒没有事件发一行注释 ": keep-alive"；一条流最长 600 秒（task.py 的 MAX_STREAM_SECONDS）
           兜底：SSE 连不上或 30 秒什么都没收到 → 每 3 秒轮询：apply 轮询 GET /apply/{id}（status 判断结束，stage 显示阶段），
                 parse 轮询 GET /resumes/{id} 的 parse_status
具体建议   同步流式响应（POST + text/event-stream），不经 pub/sub：
           event: delta {"text":"..."}  ×N                                 ← 边生成边显示
           event: done  {"text","violation_count","prompt_version","model","created_at"}   ← 数字复检后的全文，以它为准整段替换
           event: error {"code","message"}                                 ← code 50002；什么都不存，前端可以重试
面试逐轮   同步流式响应（POST + text/event-stream），不经 pub/sub：
           event: evaluation {"turn_id","skipped","score","scores","evidence","good","bad","better_answer","decision","low_evidence"}
                                                                           ← 上一题的点评，只有练习模式发；跳过的题不发
           event: topic      {"idx","label","source","count"}              ← 问到一个新话题（前端这时才显示它）
           event: asking     {"topic_idx","depth"}                         ← 开始出题，depth > 0 是追问
           event: question   {"delta":"..."}  ×N                            ← 题目逐段
           event: asked      {"turn_id","text","topic_idx","depth"}        ← 题目出完，等回答
           event: finished   {"report_ready","verdict","overall"}
           event: error      {"code","message"}                            ← 50002：模型出错，之后调 POST /start 从原处继续；
                                                                              40901：这场面试已有请求在推进，稍后再试
Nginx      nginx/default.conf：proxy_buffering off; proxy_cache off; proxy_http_version 1.1; proxy_set_header Connection '';
           proxy_read_timeout 900s；gzip_types 不含 text/event-stream
```

## 3.4 关键接口示例

**POST /interviews**（要几秒：面经太长时先切段向量化，然后一次模型调用定下话题）

```json
{ "code": 0, "message": "success", "data": {
    "id": 17, "mode": "normal",
    "gate": { "passed": true, "overall_match": 76.7, "threshold": 60.0 },
    "topic_count": 5,
    "context_mode": "full"
} }
```

只给话题个数，不给话题内容：问到哪个话题才显示哪个（GET /interviews/{id} 的 topics 也只列问到了的，结束后才是全部）。`topic_count` 是实际定下的个数，偶尔少于 5。
`context_mode`：none = 没贴面经；full = 面经不超过 3000 字，整段给面试官；retrieval = 更长，切段后按话题检索（向量化失败时退回 full，只取前 3000 字）。

**POST /interviews/{id}/answer** → SSE（练习模式）

```
event: evaluation
data: {"turn_id":203,"skipped":false,"score":67,"scores":{"correctness":4,"depth":2,"clarity":4},
       "evidence":[{"quote":"先更新数据库再删缓存","char_start":0,"char_end":10,"verify_result":"exact"}],
       "good":"说出了先更新库再删缓存的常见做法","bad":"没说为什么这么选，也没提并发下的问题",
       "better_answer":"……【接口耗时从多少降到多少】……","decision":"followup","low_evidence":false}

event: asking
data: {"topic_idx":0,"depth":1}

event: question
data: {"delta":"你刚说先更新数据库再删缓存，"}
event: question
data: {"delta":"删失败了怎么办？"}

event: asked
data: {"turn_id":204,"text":"你刚说先更新数据库再删缓存，删失败了怎么办？","topic_idx":0,"depth":1}
```

正常模式没有 evaluation 事件；换到新话题时在 asking 之前多一个 `topic`。话题用完（或花费到了单场上限）：`evaluation`（练习模式）→ `finished`。

**GET /interviews/{id}/report**（字段以 `schemas.InterviewReportOut` 为准；`report` 的完整结构见 02 2.3）

```json
{ "code": 0, "message": "success", "data": {
    "id": 17, "apply_id": 8, "job_title": "后端开发实习生（Java）", "domain": "cs", "company_name": null,
    "mode": "normal", "status": "completed", "topic_count": 5,
    "topics": [ … ],
    "turns": [ { "id": 203, "topic_idx": 0, "depth": 0, "question": "…", "answer": "…", "skipped": false, "evaluation": { … } } ],
    "waiting": false, "report_ready": true,
    "report": {
      "overall": 71, "verdict": "pass", "threshold": 60.0, "mode": "normal", "early": false, "answered": 8, "summary_ok": true,
      "topics": [ { "idx": 0, "label": "二手交易平台 · 缓存", "source": "project", "score": 73 },
                  { "idx": 2, "label": "消息队列", "source": "requirement", "score": 47 } ],
      "strengths":  [ { "title": "定位问题有方法", "detail": "慢查询那题：用 EXPLAIN 找到全表扫描……" } ],
      "weaknesses": [ { "title": "说不出成果数据", "detail": "订单模块两次被问到效果……" } ],
      "links": [ { "kind": "requirement", "ref_id": 9, "topic_idx": 2, "label": "了解消息队列", "text": "先补……" } ],
      "prompt_version": "interview-v2", "created_at": "2026-10-07T11:45:59"
    }
} }
```

`verdict`：pass / fail / practice（练习模式不下结论）/ incomplete（没聊完所有话题就结束，不下结论）。`links` 只挑得分低于 60、来源是简历问题或岗位要求的话题，前端点过去是结果页上对应的那一条。

**GET /resumes/{id}/diagnosis**：诊断状态、mode、overall_score、五维 score_detail、统计（stats，含拦截率 intercept_rate）、花费，以及 findings[]（来源、规则码 / 风险类型、严重度、证据原文与 char 区间、verify_result、rewrite）；字段以 `schemas.DiagnosisOut` 为准。
