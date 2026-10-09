"""其他方向（通用）：还没有专门领域包的专业都选它（设计、教育、法律、医药……）。

TEXTS 的每一项对应 llm/prompts.py 里的一个 [[名字]]，写法照着 cs.py，但不带任何行业：角色就叫招聘官 / 面试官，
示例挑各专业都会有的事（办公软件、毕业设计、职业资格证）。规则本来就不分专业，照常跑；
模型只能凭常识和岗位原文判断，没有专门方向准，所以页面上要说一句（NOTE，专门方向没有这一项）。
证书要求记成 other（同 finance.py 的理由：证书不进技能词典）。
"""
from app.domains import finance, ops

KEY = "general"
NAME = "其他"            # 页面上读作「其他方向」
ICON = "通用"
DESC = "设计 · 教育 · 法律 · 医药 · 其他还没单独做的方向"
RULE_HINT = "通用标准（比如经历要写清做了什么、结果怎样）"
INTERVIEW_HINT = "面试按岗位要求和你的经历提问"
INTERVIEW_LABEL = "专业面"
NOTE = "这个方向还没有专门的诊断标准，按通用标准分析，结果可能不够准，仅供参考。更多求职方向正在陆续开发，敬请期待。"
DISABLED_RULES: tuple[str, ...] = ()
# 不知道是哪一行，各方向认的结果词都认：写了指标名就是写了结果，少报几条「没写结果」
RESULT_WORDS: tuple[str, ...] = tuple(dict.fromkeys(ops.RESULT_WORDS + finance.RESULT_WORDS))

SAMPLE_JD = {
    "title": "UI 设计实习生",
    "company": "示例设计工作室",
    "text": """任职要求：
1. 本科及以上学历，视觉传达、数字媒体艺术、工业设计等相关专业；
2. 熟练使用 Figma 或 Sketch，会用 Photoshop、Illustrator；
3. 有完整的 App 或网页界面设计作品，投递时请附作品集；
4. 了解基本的交互设计原则，能写交互说明；
5. 会做简单的动效（AE 或 Principle）者优先；
6. 每周可实习 4 天以上，实习 3 个月以上；
7. 审美好，能接受修改意见，沟通顺畅。""",
}

TEXTS = {
    # 不是提示词片段：模型报出的 depth_mismatch 问题给用户看的标题
    "risk_depth_title": "专业深度与声明不匹配",
    # 诊断
    "recruiter": "招聘官",
    "risk_depth": '专业深度撑不起声明：用了"精通 / 深入 / 主导"等字眼，但描述停留在"参与了某某"',
    "risk_incoherent": "逻辑不连贯：概念、方法或数据说错了，或前后对不上",
    "diagnose_example": """{"findings": [{"risk_type": "vague", "severity": "medium", "evidence_quote": "负责部门的日常工作",
  "reason": "没有说明具体做了哪些事、带来了什么结果", "suggestion": "写明具体做法和结果"}]}""",
    # JD 解析
    "jd_skill_kind": "专业技能与工具",
    "jd_split_example": '"熟练使用 Word、PPT"',
    "jd_alt_example": '工具或软件（"会用 Excel 或 WPS"）',
    "jd_skill_desc": "具体的工具 / 软件 / 专业技能（如 Excel、PPT、Photoshop、教案设计、合同审查）",
    "jd_skill_fill": '工具、软件或技能的名字本身，照 JD 里的写法（如 "PPT"）',
    "jd_example": """{"requirements": [
  {"req_type": "hard", "category": "skill", "skill": "PPT", "quote": "熟练使用 PPT、Excel 等办公软件", "content": "熟练使用 PPT"},
  {"req_type": "plus", "category": "other", "skill": null, "quote": "持有相关职业资格证书者优先", "content": "持有相关职业资格证书"}
]}""",
    # 匹配
    "screener": "简历筛选助手",
    "match_partial": "用的是相近的工具或方法",
    "match_example": '{"results": [{"id": 3, "status": "hit", "evidence_quote": "独立完成 20 页的季度汇报 PPT，在部门例会上讲解", '
                     '"reason": "有制作和使用 PPT 的实际经历"}]}',
    # 具体建议
    "interviewer": "面试官",
    "advice_nonfacts": "工具、做法、成果",
    "advice_where": "描述",
    "gap_example": "沟通协调会问遇到分歧怎么处理、最后怎么推进到结果",
    # 模拟面试
    "interview_name": "专业面试",
    "topic_label_example": '"毕业设计 · 调研"、"沟通协调"',
    "plan_example": '{"topics": [{"source": "project", "ref": "P1", "label": "毕业设计 · 调研", '
                    '"intent": "确认调研是不是本人做的，追问样本怎么选、结论怎么得出"}, '
                    '{"source": "requirement", "ref": "R9", "label": "数据整理", '
                    '"intent": "简历里没有，确认是否会用 Excel 整理和汇总数据"}]}',
    "correctness": "专业上说得对不对（概念、方法、事实），有明显错误要扣分。",
    "knowledge": "专业知识",
    "eval_example": '{"scores": {"correctness": 4, "depth": 2, "clarity": 4}, "evidence": ["先列出每个人的任务和截止时间，再每周对一次进度"], '
                    '"good": "知道先拆任务、定时间点", "bad": "没说进度落后时怎么处理，也没给结果", "better_answer": "……", "decision": "followup"}',
    "report_example": '{"strengths": [{"title": "做事有条理", "detail": "毕业设计那题：先说调研怎么设计，再讲数据怎么分析，前后逻辑清楚"}], '
                      '"weaknesses": [{"title": "说不出成果数据", "detail": "实习经历两次被问到效果，只答了“领导挺满意的”"}], '
                      '"links": [{"ref": "F12", "text": "简历里这句也只写了做什么；先整理出能说明效果的数字或反馈，写进简历，面试时就有话说"}]}',
}
