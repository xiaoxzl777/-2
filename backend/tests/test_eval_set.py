"""诊断评测集脚本：降质版本改对了地方；跑批脚本的定位与打分逻辑。不调模型。"""
import random

from app.matching.skill_dict import SkillDict, SkillEntry
from scripts.dump_seed import load_skills
from scripts.gen_eval_set import SEED, make_base, variants
from scripts.run_eval import MATCH_KINDS, locate, match_requirements, score_run


def _variants(i=0):
    return variants(make_base(random.Random(SEED * 100 + i), i), i)


def _all_text(content) -> str:
    entries = content.education + content.work + content.projects
    return "\n".join([e.title for e in entries] + [b for e in entries for b in e.bullets]
                     + content.skills + content.awards + [content.summary])


def test_clean_base_is_clean_by_construction():
    content, defects = _variants()["clean"]
    assert defects == []
    stacks = " ".join(b for p in content.projects for b in p.bullets if b.startswith("技术栈："))
    for line in content.skills:                                   # 技能栏的每一项都在项目技术栈里出现过
        for skill in line.split("：", 1)[1].split("、"):
            assert skill in stacks
    assert [w.date for w in content.work] == ["2025.03-2025.06", "2024.12-2025.02"]   # 两段实习只隔 1 个月
    assert not any(b.startswith(("参与", "协助")) for e in content.work + content.projects for b in e.bullets)


def test_each_defect_is_drawn_where_the_ground_truth_says():
    for variant in ("rule", "semantic"):
        content, defects = _variants()[variant]
        text = _all_text(content)
        assert all(d["anchor"] in text for d in defects), variant

    content, defects = _variants()["rule"]
    assert [d["type"] for d in defects] == ["dequant", "weak_verb", "skill_unused", "timeline_gap"]
    dequant = defects[0]["anchor"]
    assert not any(ch.isdigit() for ch in dequant)                 # 去掉了数字，但留着结果词
    assert defects[1]["anchor"].startswith("协助")
    assert content.work[1].date == "2024.05-2024.08"               # 到较近那段的 2025.03 空了 7 个月

    content, defects = _variants()["semantic"]
    assert [d["expect"] for d in defects] == ["exaggeration", "incoherent", "unclear_ownership"]
    assert content.work[0].bullets[1].endswith(defects[0]["anchor"])


def test_locate_ignores_whitespace_from_line_wraps():
    text = "项目经历\n设计热门商品缓存方案，商品列表接口响应时间降低 70%"
    assert locate(text, "设计热门商品缓存方案，商品列表接口响应 时间降低 70%") == (5, len(text))
    assert locate(text, "不存在的一句话") is None


def test_score_run_counts_position_and_type_hits():
    text = "协助实现订单模块\n团队一起完成了上线"
    gt = {"a.pdf": {"variant": "rule", "defects": [
        {"type": "weak_verb", "expect": "WEAK_VERB", "anchor": "协助实现订单模块"},
        {"type": "dequant", "expect": "NO_QUANTIFICATION", "anchor": "团队一起完成了上线"}]}}
    docs = {"a.pdf": {"full_text": text, "structure": {}}}

    def finding(code, start, end, source="rule"):
        return {"source": source, "rule_code": code if source == "rule" else None,
                "risk_type": code if source == "llm" else None, "char_start": start, "char_end": end, "unit_id": None}

    runs = {"a.pdf": {"findings": [finding("WEAK_VERB", 0, 2), finding("vague", 9, 12, "llm")],
                      "llm_verified": [finding("vague", 9, 12, "llm")], "llm_rejected": [{}],
                      "cost": 0.01, "seconds": 2.0}}
    s = score_run(gt, docs, runs)
    assert s["defects"]["weak_verb"] == {"position": 1.0, "type": 1.0, "n": 1}
    assert s["defects"]["dequant"] == {"position": 1.0, "type": 0.0, "n": 1}   # 模型在那里报了别的问题
    assert s["intercept_rate"] == 0.5


def test_match_requirements_follow_the_resume_content():
    """匹配消融的 8 条要求：标准答案必须和简历（规则类降质版）的内容对得上。"""
    skills = SkillDict(SkillEntry(s["id"], s["canonical_name"], tuple(s["aliases"])) for s in load_skills())
    for i in range(20):
        reqs = match_requirements(i, skills)
        content, defects = _variants(i)["rule"]
        text = _all_text(content)
        by_kind = {r["kind"]: r for r in reqs}
        assert [r["kind"] for r in reqs] == list(MATCH_KINDS)
        assert [r["id"] for r in reqs] == list(range(1, 9))

        listed = by_kind["skill_listed"]["skill"]
        assert listed == next(d["anchor"] for d in defects if d["type"] == "skill_unused")   # 只写在技能栏
        absent = by_kind["skill_absent"]["skill"]
        assert absent not in text and absent != listed
        stack = [b for p in content.projects for b in p.bullets if b.startswith("技术栈：")]
        assert any(by_kind["skill_used"]["skill"] in s for s in stack)
        assert all(by_kind[k]["skill_id"] for k in ("skill_used", "skill_listed", "skill_absent"))   # 词典里都有
        assert by_kind["alternative"]["skill"] is None                                     # 二选一：词典判不了
        assert {r["expect"] for r in reqs} == {"hit", "partial", "miss"}
