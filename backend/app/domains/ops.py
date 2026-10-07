"""运营方向：内容 / 新媒体 / 用户 / 活动运营。

TEXTS 的每一项对应 llm/prompts.py 里的一个 [[名字]]，写法照着 cs.py：同一个位置，换成运营岗的说法和例子。
示例 JSON 用单花括号（[[...]] 是在 .format() 之后才换的，不需要转义）。
"""
KEY = "ops"
NAME = "运营"
ICON = "运营"
DESC = "内容 · 新媒体 · 用户 · 活动"
RULE_HINT = "运营岗的标准（比如活动、内容要写出数据结果）"
INTERVIEW_HINT = "面试问活动策划、数据复盘"
INTERVIEW_LABEL = "运营面"
DISABLED_RULES: tuple[str, ...] = ()

SAMPLE_JD = {
    "title": "新媒体运营实习生",
    "company": "示例传媒",
    "text": """任职要求：
1. 本科及以上学历，市场营销、新闻传播、中文等相关专业优先；
2. 熟悉小红书、抖音、微信公众号等平台的内容规则；
3. 有独立策划并执行线上活动的经历，能复盘活动数据；
4. 会用 Excel 做数据整理和透视分析，会 SQL 者优先；
5. 文字功底好，能独立撰写推文和短视频脚本；
6. 了解用户增长、A/B 测试者优先；
7. 沟通能力强，执行力强。""",
}

TEXTS = {
    # 不是提示词片段：模型报出的 depth_mismatch 问题给用户看的标题
    "risk_depth_title": "专业深度与声明不匹配",
    # 诊断
    "recruiter": "运营岗位招聘官",
    "risk_depth": '专业深度撑不起声明：用了"精通 / 深入 / 主导"等字眼，但描述停留在"参与了某某"',
    "risk_incoherent": "逻辑不连贯：方法、指标或渠道用错了，或前后对不上",
    "diagnose_example": """{"findings": [{"risk_type": "vague", "severity": "medium", "evidence_quote": "负责公众号的日常运营",
  "reason": "没有说明做了哪些事、带来了什么变化", "suggestion": "写明具体动作和数据结果"}]}""",
    # JD 解析
    "jd_skill_kind": "专业技能与工具",
    "jd_split_example": '"熟悉小红书、抖音"',
    "jd_alt_example": '工具或平台（"会用剪映或 PR"）',
    "jd_skill_desc": "具体的工具 / 平台 / 方法（如 Excel、SQL、小红书、A/B 测试）",
    "jd_skill_fill": '工具或平台的名字本身，照 JD 里的写法（如 "Excel"）',
    "jd_example": """{"requirements": [
  {"req_type": "hard", "category": "skill", "skill": "Excel", "quote": "熟练使用 Excel、SQL 做数据分析", "content": "熟练使用 Excel"},
  {"req_type": "plus", "category": "experience", "skill": null, "quote": "有百万粉丝账号运营经验者优先", "content": "有大号运营经验"}
]}""",
    # 匹配
    "screener": "运营岗位招聘的简历筛选助手",
    "match_partial": "用的是相近的工具或渠道",
    "match_example": '{"results": [{"id": 3, "status": "hit", "evidence_quote": "策划并执行双十一拉新活动，新增用户 3000 人", '
                     '"reason": "有活动策划和执行的实际经历"}]}',
    # 具体建议
    "interviewer": "运营面试官",
    "advice_nonfacts": "工具、做法、成果",
    "advice_where": "描述",
    "gap_example": "活动策划会问目标怎么定、预算怎么分、效果怎么复盘",
    # 模拟面试
    "interview_name": "运营岗面试",
    "topic_label_example": '"校园公众号 · 涨粉"、"活动复盘"',
    "plan_example": '{"topics": [{"source": "project", "ref": "P1", "label": "校园公众号 · 涨粉", '
                    '"intent": "确认涨粉方案是不是本人策划的，追问用了哪些渠道、效果怎么衡量"}, '
                    '{"source": "requirement", "ref": "R9", "label": "活动复盘", '
                    '"intent": "简历里没写复盘，确认是否会拆解转化漏斗、找出流失的环节"}]}',
    "correctness": "专业上说得对不对（方法、指标、平台规则），有明显错误要扣分。",
    "knowledge": "运营知识",
    "eval_example": '{"scores": {"correctness": 4, "depth": 2, "clarity": 4}, "evidence": ["先看各渠道的拉新成本，再把预算往低成本渠道挪"], '
                    '"good": "知道按渠道拆成本来分预算", "bad": "没说怎么判断渠道质量，也没给数据", "better_answer": "……", "decision": "followup"}',
    "report_example": '{"strengths": [{"title": "会拆数据找问题", "detail": "活动复盘那题：先拆转化漏斗，定位到落地页流失，再给出改版方案"}], '
                      '"weaknesses": [{"title": "说不出成果数据", "detail": "公众号运营两次被问到效果，只答了“涨了不少粉”"}], '
                      '"links": [{"ref": "F12", "text": "简历里这句也只写了做什么；先统计出粉丝和阅读量的变化，写进简历，面试时就有话说"}]}',
}
