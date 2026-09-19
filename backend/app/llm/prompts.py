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
