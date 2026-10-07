"""评测脚本：诊断降质版本改对了地方（计算机、运营两套素材）；匹配要求和面试回答按设计构造；跑批脚本的定位与打分逻辑。不调模型。"""
import random
import re
import statistics
from collections import Counter

import pytest

from app.diagnose.rules import _RESULT_WORDS, _WEAK_VERBS
from app.matching.skill_dict import SkillDict, SkillEntry
from scripts.dump_seed import load_skills
from scripts.gen_eval_set import POOLS, SEED, make_base, variants
from scripts.interview_answers import TIERS
from scripts.run_eval import ANSWER_SETS, MATCH_KINDS, locate, match_requirements, score_interview, score_run


POOL_KEYS = pytest.mark.parametrize("key", list(POOLS))


def _variants(i=0, key="cs"):
    pool = POOLS[key]
    return variants(make_base(random.Random(SEED * 100 + i), i, pool), i, pool)


def _skills() -> SkillDict:
    return SkillDict(SkillEntry(s["id"], s["canonical_name"], tuple(s["aliases"])) for s in load_skills())


def _all_text(content) -> str:
    entries = content.education + content.work + content.projects
    return "\n".join([e.title for e in entries] + [b for e in entries for b in e.bullets]
                     + content.skills + content.awards + [content.summary])


@POOL_KEYS
def test_clean_base_is_clean_by_construction(key):
    content, defects = _variants(key=key)["clean"]
    assert defects == []
    stacks = " ".join(b for p in content.projects for b in p.bullets if b.startswith(f"{POOLS[key].stack_label}："))
    for line in content.skills:                                   # 技能栏的每一项都在项目技术栈里出现过
        for skill in line.split("：", 1)[1].split("、"):
            assert skill in stacks
    assert [w.date for w in content.work] == ["2025.03-2025.06", "2024.12-2025.02"]   # 两段实习只隔 1 个月
    assert not any(b.startswith(("参与", "协助")) for e in content.work + content.projects for b in e.bullets)


@POOL_KEYS
def test_each_defect_is_drawn_where_the_ground_truth_says(key):
    for variant in ("rule", "semantic"):
        content, defects = _variants(key=key)[variant]
        text = _all_text(content)
        assert all(d["anchor"] in text for d in defects), variant

    content, defects = _variants(key=key)["rule"]
    assert [d["type"] for d in defects] == ["dequant", "weak_verb", "skill_unused", "timeline_gap"]
    dequant = defects[0]["anchor"]
    assert not any(ch.isdigit() for ch in dequant)                 # 去掉了数字，但留着结果词
    assert defects[1]["anchor"].startswith("协助")
    assert content.work[1].date == "2024.05-2024.08"               # 到较近那段的 2025.03 空了 7 个月

    content, defects = _variants(key=key)["semantic"]
    assert [d["expect"] for d in defects] == ["exaggeration", "incoherent", "unclear_ownership"]
    assert content.work[0].bullets[1].endswith(defects[0]["anchor"])


@POOL_KEYS
def test_pool_content_triggers_exactly_the_planned_defects(key):
    """素材本身：原句带数字、去量化的说法没有数字但有结果词（规则才会报）；没有以弱动词开头的描述；
    技能栏多写的那些技能词典都认识，任何版本的经历和自我评价里都没提到它们（连别名也没有）。"""
    pool, skills = POOLS[key], _skills()
    pairs = [b for bullets in pool.internships.values() for b in bullets] + [b for _, _, bs in pool.projects for b in bs]
    for sentence, dequant in pairs:
        assert any(ch.isdigit() for ch in sentence) and not any(ch.isdigit() for ch in dequant), sentence
        assert _RESULT_WORDS.search(dequant) and not _WEAK_VERBS.match(sentence), sentence
    unused = {skills.lookup(name) for name in pool.unused}
    assert None not in unused
    for i in range(pool.n_bases):
        for variant, (content, _) in _variants(i, key).items():
            entries = content.education + content.work + content.projects
            text = "\n".join([e.title for e in entries] + [b for e in entries for b in e.bullets] + [content.summary])
            assert not unused & {sid for sid, _, _ in skills.find(text)}, (i, variant)


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


@POOL_KEYS
def test_match_requirements_follow_the_resume_content(key):
    """匹配消融的 8 条要求：标准答案必须和简历（规则类降质版）的内容对得上。"""
    pool, skills = POOLS[key], _skills()
    for i in range(pool.n_bases):
        reqs = match_requirements(i, skills, pool)
        content, defects = _variants(i, key)["rule"]
        text = _all_text(content)
        by_kind = {r["kind"]: r for r in reqs}
        assert [r["kind"] for r in reqs] == list(MATCH_KINDS)
        assert [r["id"] for r in reqs] == list(range(1, 9))

        listed = by_kind["skill_listed"]["skill"]
        assert listed == next(d["anchor"] for d in defects if d["type"] == "skill_unused")   # 只写在技能栏
        absent = by_kind["skill_absent"]["skill"]
        assert absent not in text and absent != listed
        stack = [b for p in content.projects for b in p.bullets if b.startswith(f"{pool.stack_label}：")]
        assert any(by_kind["skill_used"]["skill"] in s for s in stack)
        assert all(by_kind[k]["skill_id"] for k in ("skill_used", "skill_listed", "skill_absent"))   # 词典里都有
        assert by_kind["alternative"]["skill"] is None                                     # 二选一：词典判不了
        assert {r["expect"] for r in reqs} == {"hit", "partial", "miss"}


@POOL_KEYS
def test_interview_answers_are_built_as_designed(key):
    """面试评分的 12 题（计算机、运营各一套）：每个项目 2 题；"具体"档带着简历那条描述的结果数字；
    "答错"和"具体"篇幅相近，"空泛"明显短。"""
    bullets = {name: [b for b, _ in items] for name, _, items in POOLS[key].projects}
    questions = ANSWER_SETS[key].QUESTIONS
    assert Counter(q["project"] for q in questions) == dict.fromkeys(bullets, 2)
    for q in questions:
        a = q["answers"]
        assert tuple(a) == TIERS
        assert all(n in a["good"] for n in re.findall(r"\d+(?:\.\d+)?", bullets[q["project"]][q["bullet"]])), q["label"]
        assert len(a["wrong"]) >= 0.7 * len(a["good"]) and len(a["vague"]) <= 0.5 * len(a["good"]), q["label"]


def test_score_interview_order_stability_and_evidence():
    def g(score, c, d, cl, calls=1, low=False, method="exact"):
        return {"score": score, "scores": {"correctness": c, "depth": d, "clarity": cl}, "low_evidence": low,
                "evidence": [] if low else [{"verify_result": method}], "calls": calls, "cost": 0.002, "seconds": 3.0}

    run1 = [{"good": g(87, 5, 4, 4), "vague": g(60, 4, 1, 4), "wrong": g(40, 1, 3, 3)},
            {"good": g(80, 4, 4, 4, method="fuzzy"), "vague": g(80, 4, 4, 4, calls=2), "wrong": g(60, 3, 3, 3, low=True)}]
    run2 = [{"good": g(87, 5, 4, 4), "vague": g(67, 2, 3, 5), "wrong": g(40, 1, 3, 3)},
            {"good": g(80, 4, 4, 4), "vague": {"error": "x", "calls": 2}, "wrong": g(60, 3, 3, 3, low=True)}]
    s = score_interview([run1, run2])
    assert s["order"] == {"vague": [0.5, 1.0], "wrong": [1.0, 1.0]}   # 同分算没分开；失败的那条不计
    assert s["tiers"]["good"]["score"] == 83.5
    assert s["aimed"] == {"vague": pytest.approx(2 / 3), "wrong": 1.0}  # run2 第 1 题的空泛回答扣得最多的是正确性
    assert s["score_stdev"] == pytest.approx(statistics.stdev([60, 67]) / 5)   # 5 条回答打了两次分，只有一条变了
    assert s["same_score"] == 0.8
    assert (s["first_pass"], s["low_evidence"], s["exact_quotes"], s["errors"]) == \
        (pytest.approx(10 / 11), pytest.approx(2 / 11), pytest.approx(8 / 9), 1)
