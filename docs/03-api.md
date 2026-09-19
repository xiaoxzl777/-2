> Exported from design plan v3 (2026-09-18). Source of truth: this docs/ folder; update docs before changing code.

# 三、接口设计

统一前缀 `/api/v1`；所有接口（含 SSE）用 `Authorization: Bearer <token>`，SSE 前端用 fetch-event-source（支持 POST）。
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

## 3.2 接口清单（26 个）

```
认证 3    POST /auth/register   POST /auth/login   GET /auth/me

简历 7    POST   /resumes                  → {id, task_id:"parse:{id}"}
          GET    /resumes                  GET /resumes/{id}                DELETE /resumes/{id}
          GET    /resumes/{id}/blocks      GET /resumes/{id}/structure      PATCH /resumes/{id}/structure

诊断 1    GET  /resumes/{id}/diagnosis     ?diagnosis_id=      诊断由投递触发，这里只查结果

进度 1    GET  /tasks/{kind}/{id}/stream   SSE；kind ∈ {parse, apply}

投递 2    POST /apply  {resume_id, job_id, diagnose_mode?, match_mode?, model?} → {id, diagnosis_id, task_id:"apply:{id}", status}   图 A
                       投递 id = match_report_id；简历还在解析也可以投，后台任务先等解析完成
          GET  /apply/{id}  → status / stage / gate{passed, overall_match, threshold} / dimension_scores / resume_score
                       + gaps[]（未满足与部分满足的要求，重要的在前）+ resume_issues[]（诊断里最严重的 8 条，带 finding id）

岗位 4    POST /jobs   {title, company?, raw_text}         同步解析（一次模型调用，约 2–4 秒）→ 岗位 + requirements[]
                                                           每条要求带 JD 原文引用 quote 与 char 区间；定位不到的丢弃；失败则不保存
          GET  /jobs   ?include_templates=1               GET /jobs/{id}        DELETE /jobs/{id}（软删除；模板不可删）

匹配 1    GET  /match/{id}     匹配由投递触发，这里只查报告（id = 投递 id）
                       → status / overall_match / passed / threshold / dimension_scores / items[]
                       items[] 每条 = 要求项内容 + status(hit|partial|miss) + matched_by(dict|profile|fulltext)
                       + reason + 简历原文依据 evidence_quote 与 char 区间

改写 1    POST /findings/{id}/rewrite?use_rag=&use_rerank=

面试 5    POST /interviews                 {resume_id, job_id, company_name?, extra_context?, practice?}
                                           → {id, gate:{passed, overall_match, threshold}, mode, plan_summary}
          POST /interviews/{id}/start      → SSE：question 流
          POST /interviews/{id}/answer     {text} → SSE：evaluation → question 流 | round_end | finished
          GET  /interviews/{id}            会话 + turns
          GET  /interviews/{id}/report

系统 1    GET /system/info                 模型列表 + 规则清单 + 用量（用量需 admin）
```

## 3.3 异步任务与 SSE 契约

```
后台任务   task_id="{kind}:{id}"，kind ∈ {parse, apply}；apply 的 stage ∈ parsing/analyzing/diagnose/match/gate（diagnose 与 match 并行，先完成的先到）；Redis pub/sub channel task:{kind}:{id}
           event: progress {"stage","percent","message"} / done {"kind","id","status"} / error {"code","message"}
           progress 来自 Redis 频道（只有 apply 会发）；done {"kind","id","status"} / error 以数据库里的任务状态为准，
           SSE 接口每秒顺带查一次——连上来时任务已结束、或中途漏了消息，都一定能收到结束事件；15s 无事件发一行 ": keep-alive"
           兜底：SSE 连不上或 30s 无事件 → 每 3s 轮询对应资源 status（apply 轮询 GET /apply/{id} 的 stage）
面试逐轮   同步流式响应（POST + text/event-stream），不经 pub/sub：
           event: evaluation {"turn_id","scores","feedback","decision"}      ← 上一题的评估（answer 接口才有）
           event: question   {"turn_id","delta":"..."}  ×N                   ← 下一问逐 token
           event: round_end  {"round":"tech","score":72}
           event: finished   {"report_ready":true}
Nginx      proxy_buffering off; proxy_cache off; proxy_http_version 1.1; proxy_set_header Connection '';
           proxy_read_timeout 900s; gzip 不含 text/event-stream；FastAPI 响应带 X-Accel-Buffering: no
```

## 3.4 关键接口示例

**POST /interviews**

```json
{ "code": 0, "data": {
    "id": 17, "mode": "normal",
    "gate": { "passed": true, "overall_match": 76.0, "threshold": 60 },
    "plan_summary": {
      "tech": [ { "idx": 0, "intent": "深挖订单服务 P99 优化的瓶颈定位方法", "linked_type": "finding", "linked_id": 501 },
                { "idx": 1, "intent": "考察微服务经验（JD 加分项，简历未体现）", "linked_type": "requirement", "linked_id": 2 } ],
      "hr":   [ { "idx": 5, "intent": "实习经历中的职责边界与协作", "linked_type": "finding", "linked_id": 512 } ] }
} }
```

**POST /interviews/{id}/answer** → SSE

```
event: evaluation
data: {"turn_id":203,"scores":{"correctness":4,"depth":3,"clarity":4},
       "evidence":[{"quote":"先用 arthas 看了线程栈，发现锁在库存扣减","verify_result":"exact"}],
       "feedback":"定位方法具体可信；但未说明优化后如何验证","decision":"followup"}

event: question
data: {"turn_id":204,"delta":"优化"}
event: question
data: {"turn_id":204,"delta":"之后你是怎么验证 P99 确实降下来的？"}

event: round_end
data: {"round":"tech","score":72}
```

**GET /interviews/{id}/report**

```json
{ "code": 0, "data": {
    "round_scores": { "tech": 72, "hr": 81 }, "overall": 75.6, "verdict": "pass",
    "strengths": ["性能问题定位思路清晰"],
    "weaknesses": ["微服务相关经验薄弱", "回答缺少量化验证"],
    "linked_findings": [501, 512],
    "turns_review": [ { "turn_id": 203, "question": "...", "answer": "...", "scores": {}, "evidence": [], "better_answer": "..." } ]
} }
```

**GET /resumes/{id}/diagnosis** 与 **POST /findings/{id}/rewrite** 示例同 v2（略）。
