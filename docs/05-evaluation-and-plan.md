> Exported from design plan v3 (2026-09-18). Source of truth: this docs/ folder; update docs before changing code.

# 七、里程碑（约 12 周，每周 15–20 小时；总周期 8 个月，余量充足）

| # | 里程碑 | 时长 | 完成标准 |
|---|---|---|---|
| M0 | 骨架 + 文档 + 建表 + 数据 | 3 天 | `git init` + `.gitignore` + 首次提交；docs/ 四份文档；手动执行 `backend/sql/schema.sql` 建出 11 张表；compose 骨架；`data/resumes/` ≥20 份 PDF（≥8 两栏/侧边栏、≥4 表格型、DOCX ≥2）；`skills_seed.csv` 100–200 条；JD 来源跑通 ≥30 条 |
| M1 | 解析内核 | 1.5 周 | 三路分流；region-first + 表格；full_text 契约单测全过；版面合成集脚本可跑 |
| M2 | 结构化 + 后端骨架 | 1 周 | 上传 → structure（block_ids、summary、skill_mentions）；**Upload 页** |
| M3 | 诊断引擎 | 1.5 周 | 三种 mode 跑通；findings 带 verify_result；成本预检；SSE |
| M4 | 分析主界面 | 1 周 | **Analysis 页**：文本高亮 + FindingPanel 联动 |
| M5 | 本体 + 匹配 + 初筛 + JD 语料 | 1.5 周 | 进入条件 JD ≥200；三路判定；匹配报告含 passed；岗位模板；**JobMatch 页** |
| M6 | 案例库 + 改写 | 1 周 | 进入条件 cases ≥100；rewrite 接口 + 占位符复检；**Rewrite 页** |
| M7 | 模拟面试 | 2 周 | 计划 / 逐轮 / 评估 evidence 校验 / 报告 / 续答 / 24h 清理；**Interview、InterviewReport 页** |
| M8 | 评测 + 消融 | 1.5 周 | 必做四组 + 面试模块评测（8.4） |
| M9 | 部署 + 打磨 | 0.5 周 | compose 一键起；Nginx SSE 验证 |

JD 与案例采集在 M1–M4 用碎片时间并行。每个里程碑完成后先自己跑通、能口头讲清实现，再进下一阶段。

---

# 八、评估方案

## 8.1 评测集构成与局限

```
程序化降质（规则类，GT 自动）：删量化数字 / 强动词降级 / 删技能提及 / 造时间空窗 / 套表格模板
程序化降质（语义类，只有 LLM 通道能检，注入在 bullet 正文）：夸大注入 / 逻辑矛盾注入 / 职责混合注入；判分为位置命中，risk_type 另报类型准确率
人工审核（精确率）：20–30 份真实简历跑 hybrid，2 名同学对每条 LLM finding 二元判定 → LLM 精确率、κ、残留幻觉率
局限：降质只覆盖预设缺陷；语义类边界模糊；人工样本小；第三方 API 静默升级（以 model_version 记录）
```

## 8.2 版面解析评测

合成集：20 份内容 × 3 模板 = 60 份 PDF（PyMuPDF 逐栏绘制，GT = 渲染 line 顺序，评测时打乱）；真实集 20 份可砍。指标：相邻行对顺序准确率、文档级全对率。对照：PyMuPDF sort=True / 启发式 / 启发式+LLM 兜底。

## 8.3 实验分级

```
必做
 (1) 解析三路对照（仅 PDF）
 (2) 本体对齐阶梯：30 对简历-JD ≈ 300 条要求项人工标 hit/partial/miss；alias → +ontology → +embedding → +rerank 一致率；各路占比
 (3) 溯源：拦截率、定位准确率（降质集）、残留幻觉率（人工）
 (4) 架构消融：rule_only / llm_only / hybrid，分「规则类子集 / 语义类子集」两张表
可选
 (5) 模型对比：deepseek-chat vs 硅基流动托管 Qwen
 (6) 改写 RAG：占位符合规率 + 规则复检通过率；30 条 pairwise LLM-judge
```

## 8.4 模拟面试评测

```
问题相关性   2 名同学对 60 道生成问题按"与简历/JD 相关、有针对性"打 1–5，报均值与 κ
薄弱点覆盖率 诊断 top-5 findings 被面试计划 linked 的比例
评分一致性   30 条真实回答：人工 1–5 打分 vs 系统分 Spearman ρ；同一回答 --repeat 3 的标准差
evidence 有效率  面试评分 evidence 经 locate_span 通过的比例（与诊断拦截率同口径）
小规模试用   5–10 名同学各完整跑一场（tech+hr），5 题满意度问卷（可选）
```

## 8.5 可复现性说明

固定 `prompt_version`；记录 `model_version` 与运行日期；评测绕过缓存；每组 `--repeat 3` 报均值±标准差；集中一周内跑完。

---

# 九、验证方式

1. **契约**：`test_fulltext_contract.py` 断言 `full_text[b.char_start:b.char_end] == b.text`
2. **解析**：`run_eval.py --task layout` 输出 8.2 指标表
3. **溯源**：`findings.verify_result='failed'` 首轮占比；面试 evidence 通过率
4. **诊断**：降质样本跑批比对
5. **匹配**：8.3 (2) 标注集一致率
6. **面试策略**：`test_interview_policy.py` 覆盖 追问上限 / 预算耗尽 / 轮次切换 / 成本熔断 / 空答
7. **端到端**：`docker compose up -d` 后：上传 → 诊断 → 贴 JD → 初筛 → 面试两轮 → 报告 → 改写
8. **中断**：面试中 kill 进程后重启，会话可续答；24h 清理生效

---

# 十、待确认与未来工作

待确认：开题/中期时间节点；是否公网部署；简历样本与面经材料可获取量；DeepSeek / 硅基流动 key，MySQL / Redis 连接信息；初筛阈值默认 60 是否合适。

未来工作：HR 端批量筛选（v2 设计可直接复用）；采纳改写生成新版本（重新解析建立新坐标系）；面经库（按公司+岗位检索）；语音面试；LangGraph checkpoint；扫描件 OCR；任务队列横向扩容。
