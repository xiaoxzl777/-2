"""计算机方向（默认方向）。

TEXTS 是从改造前的提示词里逐字截出来的：计算机方向生成的提示词和改造前完全一样，
缓存不失效，M8 的评测结果也还对应现在的代码（tests/test_domains.py 用快照核对）。
唯一有意改过的是 eval_example、report_example 两个示例：原来是双花括号（面试评分、总结的提示词不经过 .format()，
模型收到的就是 {{ }}），interview-v2 改成了单花括号，快照随之重拍。
"""
KEY = "cs"
NAME = "计算机"
ICON = "计算"
DESC = "后端 · 前端 · 算法 · 测试 · 数据"
RULE_HINT = "技术岗的标准（比如技能栏写的技术，要在项目里用过）"
INTERVIEW_HINT = "面试问技术实现、方案取舍"
INTERVIEW_LABEL = "技术面"
DISABLED_RULES: tuple[str, ...] = ()
RESULT_WORDS: tuple[str, ...] = ()   # 通用的结果词（diagnose/rules.py）本来就是按技术岗写的，不用加

SAMPLE_JD = {
    "title": "后端开发实习生",
    "company": "示例科技",
    "text": """任职要求：
1. 本科及以上学历，计算机相关专业；
2. 熟悉 Java，熟悉 Spring Boot、MyBatis 等常用框架；
3. 熟悉 MySQL，有 SQL 调优经验者优先；
4. 有 Redis 使用经验，了解常见缓存问题；
5. 了解消息队列（Kafka / RocketMQ）；
6. 有高并发场景经验者优先；熟悉 Linux 常用命令；
7. 良好的沟通能力与团队协作意识。""",
}

# 提示词片段：llm/prompts.py 里的 [[名字]] → 这里的文字
TEXTS = {
    # 不是提示词片段：模型报出的 depth_mismatch 问题给用户看的标题
    "risk_depth_title": "技术深度与声明不匹配",
    'recruiter': '技术招聘官',
    'risk_depth': '技术深度撑不起声明：用了"精通 / 深入 / 主导"等字眼，但描述停留在"使用了某某"',
    'risk_incoherent': '逻辑不连贯：技术的用途说错了，或前后对不上',
    'diagnose_example': """{"findings": [{"risk_type": "vague", "severity": "medium", "evidence_quote": "负责系统的优化工作",
  "reason": "没有说明优化了什么、用了什么手段", "suggestion": "写明优化对象与具体做法"}]}""",
    'jd_skill_kind': '技术技能',
    'jd_split_example': '"熟悉 Redis、MySQL"',
    'jd_alt_example': '技术（"了解 RabbitMQ 或 Kafka"）',
    'jd_skill_desc': '具体的语言 / 框架 / 工具 / 技术',
    'jd_skill_fill': '技术名词本身，照 JD 里的写法（如 "Redis"）',
    'jd_example': """{"requirements": [
  {"req_type": "hard", "category": "skill", "skill": "Redis", "quote": "熟悉 Redis、MySQL 等常用中间件", "content": "熟悉 Redis"},
  {"req_type": "plus", "category": "experience", "skill": null, "quote": "有高并发项目经验者优先", "content": "有高并发项目经验"}
]}""",
    'screener': '技术招聘的简历筛选助手',
    'match_partial': '用的是相近技术',
    'match_example': '{"results": [{"id": 3, "status": "hit", "evidence_quote": "基于 Redisson 分布式锁落地过秒杀防超卖方案", "reason": "有分布式锁的实际落地经验"}]}',
    'interviewer': '技术面试官',
    'advice_nonfacts': '技术、做法、成果',
    'advice_where': '技术栈或描述',
    'gap_example': '消息队列会问可靠投递、重复消费、消息积压',
    'interview_name': '技术面试',
    'topic_label_example': '"二手交易平台 · 缓存"、"消息队列"',
    'plan_example': '{"topics": [{"source": "project", "ref": "P1", "label": "二手交易平台 · 缓存", "intent": "确认缓存方案是不是本人设计的，追问一致性怎么保证、效果怎么验证"}, {"source": "requirement", "ref": "R9", "label": "消息队列", "intent": "简历里没有，确认是否了解可靠投递、重复消费这些基本问题"}]}',
    'correctness': '技术上说得对不对，有明显错误要扣分。',
    'knowledge': '技术知识',
    'eval_example': '{"scores": {"correctness": 4, "depth": 2, "clarity": 4}, "evidence": ["先更新数据库，再删掉缓存"], "good": "说出了先更新库再删缓存的常见做法", "bad": "没说为什么这么选，也没提并发下的问题", "better_answer": "……", "decision": "followup"}',
    'report_example': '{"strengths": [{"title": "定位问题有方法", "detail": "慢查询那题：用 EXPLAIN 找到全表扫描，再建联合索引，还给出了前后耗时"}], "weaknesses": [{"title": "说不出成果数据", "detail": "订单模块两次被问到效果，只答了“比较稳定”"}], "links": [{"ref": "F12", "text": "简历里这句也只写了做什么；先统计出上线后的数据，写进简历，面试时就有话说"}]}',
}
