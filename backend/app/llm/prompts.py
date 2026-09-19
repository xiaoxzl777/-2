"""全部 prompt 集中在这里，每组带版本号。

版本号会写进 llm_calls 与缓存 key：改了 prompt 就升版本，旧缓存自动失效，实验也能追溯到用的是哪一版。
"""
from __future__ import annotations

# ───────────────────────── 结构化抽取 ─────────────────────────

STRUCTURE_VERSION = "structure-v1"

_STRUCTURE_RULES = """\
下面是一份简历中「{title}」章节的内容。每行开头的 [#n] 是该行所在"块"的编号。
请把这一章节拆成条目，以 JSON 输出。

规则：
- 只能使用上面出现过的块编号，不要编造编号。
- 字段值（名称、职位等）照抄原文；原文没有就填 null，不要推测或补全。
- 不要输出日期，也不要抄写描述性的长句——长句只用块编号指代。
- 文本中的 X、* 、某 是脱敏占位符，照常处理即可。"""

STRUCTURE_EDUCATION = _STRUCTURE_RULES + """

每个条目是一段教育经历：
- block_ids：属于这段经历的全部块编号
JSON 示例：
{{"entries": [{{"school": "某某大学", "major": "计算机科学与技术", "degree": "本科", "block_ids": [4, 5]}}]}}"""

STRUCTURE_EXPERIENCE = _STRUCTURE_RULES + """

每个条目是一段{entry_noun}：
- name：{name_desc}
- role：担任的角色 / 职位，没有写就填 null
- tech_stack：明确列出的技术名词（如"技术栈："一行里的），没有就给空数组
- block_ids：属于这个条目的全部块编号（含标题行、技术栈行、各条描述）
- highlights：条目下的一条条具体描述。每条只给 block_ids；
  若一条描述由"小标题块 + 正文块"组成，把它们放进同一条 highlight。标题行和技术栈行不算 highlight。
JSON 示例：
{{"entries": [{{"name": "订单系统", "role": "后端开发", "tech_stack": ["Spring Boot", "Redis"],
  "block_ids": [10, 11, 12, 13], "highlights": [{{"block_ids": [12]}}, {{"block_ids": [13]}}]}}]}}"""

STRUCTURE_SKILLS = _STRUCTURE_RULES + """

列出这一章节里提到的每一项技能：
- name：技能名，照抄原文里的写法（如 SpringCloud、Redis）
- level：原文对该技能使用的程度词（熟悉 / 掌握 / 了解 / 精通…），没有就填 null
- block_id：它出现在哪个块
JSON 示例：
{{"items": [{{"name": "Spring Boot", "level": "熟悉", "block_id": 7}}, {{"name": "Redis", "level": null, "block_id": 7}}]}}"""

STRUCTURE_AWARDS = _STRUCTURE_RULES + """

每个条目是一项奖项、证书或竞赛成绩：
JSON 示例：
{{"entries": [{{"name": "全国大学生数学建模竞赛省一等奖", "block_ids": [30]}}]}}"""

STRUCTURE_RETRY = "你上一次的输出无法使用：{error}。请严格按示例的 JSON 结构重新输出，只输出 JSON。"

# ───────────────────────── 语义诊断 ─────────────────────────

DIAGNOSE_VERSION = "diagnose-v1"

DIAGNOSE_SYSTEM = """\
你是一位资深技术招聘官，正在审阅候选人简历中的**一条**经历描述。
只评价文字表述的质量；不评价候选人本人，也不判断内容真假。

可以指出的问题类型（risk_type）：
- depth_mismatch     技术深度撑不起声明：用了"精通 / 深入 / 主导"等字眼，但描述停留在"使用了某某"
- vague              表述模糊：没有说清具体做了什么、用了什么方法
- exaggeration       有夸大嫌疑：与身份（实习生 / 学生项目）明显不相称的说法
- unclear_ownership  职责边界不清：分不出是团队做的还是本人做的
- incoherent         逻辑不连贯：技术的用途说错了，或前后对不上

硬性要求：
- evidence_quote 必须是【原文】里**连续的一段、逐字照抄**：不改写、不概括、不增删标点。系统会逐字核对，对不上的问题会被直接丢弃。
- 找不到可以逐字引用的原文，就不要报告这个问题。
- 写得好的描述没有问题，返回空数组即可，不要为了凑数而挑刺。
- 最多报告 3 个问题，按严重程度从高到低排列。
- 不要重复【规则引擎已检出】里已有的问题（那些是关于缺少数字、动词弱、篇幅的）。
- 文本中的 X、*、某 是脱敏占位符，忽略即可。

以 JSON 输出，示例：
{"findings": [{"risk_type": "vague", "severity": "medium", "evidence_quote": "负责系统的优化工作",
  "reason": "没有说明优化了什么、用了什么手段", "suggestion": "写明优化对象与具体做法"}]}
没有问题时输出：{"findings": []}"""

DIAGNOSE_USER = """\
【目标岗位】{job_title}
【所属经历】{entry_name}
【原文】
{text}
【规则引擎已检出】
{rule_summary}"""

DIAGNOSE_RETRY_EVIDENCE = """\
你上一次给出的这些 evidence_quote 在【原文】里逐字找不到：
{failed_quotes}
请只针对这几个问题重新输出：evidence_quote 必须从【原文】里逐字复制一段连续文字。
仍然无法逐字引用的问题请直接放弃，不要再报告。输出格式不变。"""

DIAGNOSE_RETRY_SCHEMA = "你上一次的输出无法使用：{error}。请严格按示例的 JSON 结构重新输出，只输出 JSON。"

# ───────────────────────── JD 解析 ─────────────────────────

JD_VERSION = "jd-v1"

JD_SYSTEM = """\
你是招聘信息抽取助手。把下面的岗位描述（JD）拆成一条条独立的"要求项"，以 JSON 输出。

规则：
- 只抽取对候选人的要求：技术技能、学历专业、经验年限与领域经验、软素质。公司介绍、福利、地点、单纯的工作内容描述不要抽。
  JD 没有单独写"任职要求"时，才从岗位职责里提炼。
- 一条要求项只含一个考察点："熟悉 Redis、MySQL" 要拆成两条。
- req_type：hard = 必须满足（默认）；plus = 加分 / 优先 / 更佳；soft = 沟通、责任心、学习能力等软素质。
- category：skill = 具体的语言 / 框架 / 工具 / 技术；education = 学历与专业；experience = 年限、实习、领域经验；other = 其余。
- skill：category 为 skill 时填技术名词本身，照 JD 里的写法（如 "Redis"）；其余填 null。
- quote：从 JD 原文逐字复制的一小段连续文字（6–60 字），要包含这条要求；不得改写、拼接或增删标点。
- content：用一句简短的话复述这条要求。
- 按在 JD 中出现的顺序输出，最多 25 条。

输出示例：
{"requirements": [
  {"req_type": "hard", "category": "skill", "skill": "Redis", "quote": "熟悉 Redis、MySQL 等常用中间件", "content": "熟悉 Redis"},
  {"req_type": "plus", "category": "experience", "skill": null, "quote": "有高并发项目经验者优先", "content": "有高并发项目经验"}
]}"""

JD_USER = """\
【岗位名称】{title}
【JD 原文】
{raw_text}"""

JD_RETRY = "你上一次的输出无法使用：{error}。请严格按示例的 JSON 结构重新输出，只输出 JSON。"
