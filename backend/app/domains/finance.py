"""财会金融方向：会计 / 审计 / 财务分析 / 税务 / 证券研究。

TEXTS 的每一项对应 llm/prompts.py 里的一个 [[名字]]，写法照着 cs.py：同一个位置，换成财会岗的说法和例子。
示例 JSON 用单花括号（[[...]] 是在 .format() 之后才换的，不需要转义）。
证书（CPA、ACCA、初级会计……）不进技能词典：简历里证书多半写在「技能证书」一栏，会被归到技能，
「技能栏写了、经历里没用过」这条规则会对每个证书报一次；所以 JD 里的证书要求记成 other，交给模型按全文判断（见 jd_example）。
"""
KEY = "finance"
NAME = "财会金融"
ICON = "财会"
DESC = "会计 · 审计 · 财务分析 · 税务 · 证券研究"
RULE_HINT = "财会岗的标准（比如做过的账务、审计工作要写出规模和结果）"
INTERVIEW_HINT = "面试问会计处理、报表分析"
INTERVIEW_LABEL = "专业面"
DISABLED_RULES: tuple[str, ...] = ()
# 财会写结果的说法（通用的结果词见 diagnose/rules.py）。和运营一样只收指标名
RESULT_WORDS: tuple[str, ...] = ("准确率", "差错率", "零差错", "回款率", "完成率", "收益率", "节税")

SAMPLE_JD = {
    "title": "审计实习生",
    "company": "示例会计师事务所",
    "text": """任职要求：
1. 本科及以上学历，会计学、审计学、财务管理等相关专业；
2. 了解审计基本流程，熟悉企业会计准则；
3. 有函证、存货监盘或审计底稿编制经历者优先；
4. 熟练使用 Excel，会用用友或金蝶等财务软件；
5. 通过 CPA 部分科目者优先；
6. 能适应出差，每周可实习 4 天以上；
7. 细心，有责任心，沟通能力好。""",
}

TEXTS = {
    # 不是提示词片段：模型报出的 depth_mismatch 问题给用户看的标题
    "risk_depth_title": "专业深度与声明不匹配",
    # 诊断
    "recruiter": "财会岗位招聘官",
    "risk_depth": '专业深度撑不起声明：用了"精通 / 深入 / 主导"等字眼，但描述停留在"参与了某某"',
    "risk_incoherent": "逻辑不连贯：会计处理、指标或计算说错了，或前后对不上",
    "diagnose_example": """{"findings": [{"risk_type": "vague", "severity": "medium", "evidence_quote": "负责公司的日常账务处理",
  "reason": "没有说明处理了哪些业务、规模多大", "suggestion": "写明业务范围、凭证量和结果"}]}""",
    # JD 解析
    "jd_skill_kind": "专业技能与软件",
    "jd_split_example": '"熟悉用友、金蝶"',
    "jd_alt_example": '软件（"会用用友或金蝶"）',
    "jd_skill_desc": "具体的软件 / 方法 / 业务（如用友、Excel、成本核算、DCF 估值）",
    "jd_skill_fill": '软件或方法的名字本身，照 JD 里的写法（如 "Excel"）',
    "jd_example": """{"requirements": [
  {"req_type": "hard", "category": "skill", "skill": "Excel", "quote": "熟练使用 Excel 及用友等财务软件", "content": "熟练使用 Excel"},
  {"req_type": "plus", "category": "other", "skill": null, "quote": "通过 CPA 部分科目者优先", "content": "通过 CPA 部分科目"}
]}""",
    # 匹配
    "screener": "财会岗位招聘的简历筛选助手",
    "match_partial": "用的是相近的软件或方法",
    "match_example": '{"results": [{"id": 3, "status": "hit", "evidence_quote": "负责 3 家客户的应收账款函证，回函率从 70% 提升到 92%", '
                     '"reason": "有函证的实际经历"}]}',
    # 具体建议
    "interviewer": "财会面试官",
    "advice_nonfacts": "软件、做法、成果",
    "advice_where": "描述",
    "gap_example": "审计会问函证怎么控制、监盘发现差异怎么处理",
    # 模拟面试
    "interview_name": "财会岗面试",
    "topic_label_example": '"审计实习 · 函证"、"DCF 估值"',
    "plan_example": '{"topics": [{"source": "project", "ref": "P1", "label": "审计实习 · 函证", '
                    '"intent": "确认函证是不是本人做的，追问怎么控制回函、回函不符怎么处理"}, '
                    '{"source": "requirement", "ref": "R9", "label": "DCF 估值", '
                    '"intent": "简历里没有估值经历，确认是否理解自由现金流和折现率怎么定"}]}',
    "correctness": "专业上说得对不对（会计处理、准则、税法、计算），有明显错误要扣分。",
    "knowledge": "财会知识",
    "eval_example": '{"scores": {"correctness": 4, "depth": 2, "clarity": 4}, "evidence": ["先拿银行对账单逐笔核对，再编余额调节表找未达账项"], '
                    '"good": "知道用余额调节表找差异", "bad": "没说未达账项有哪几类、之后怎么跟进", "better_answer": "……", "decision": "followup"}',
    "report_example": '{"strengths": [{"title": "账务处理有条理", "detail": "存货那题：先说盘点差异怎么查，再给出调账分录，前后逻辑清楚"}], '
                      '"weaknesses": [{"title": "说不出成果数据", "detail": "报销审核两次被问到效果，只答了“差错少了”"}], '
                      '"links": [{"ref": "F12", "text": "简历里这句也只写了做什么；先统计出凭证量和差错率的变化，写进简历，面试时就有话说"}]}',
}
