from datetime import date

import pytest

from app.matching.matcher import MatchItem, degree_level, experience_years, match_by_rules, score_match

TODAY = date(2026, 9, 1)
TEXT = "\n".join([
    "某某大学 计算机科学与技术 本科 2023.09-2027.06",          # 0
    "熟悉 Java、Redis、Docker",                                 # 1  技能清单
    "订单系统 后端开发",                                        # 2
    "热点商品数据预热至 Redis，列表查询响应从 820ms 降至 140ms。",  # 3  项目经历
])
LINES = TEXT.split("\n")


def _at(line_no: int, word: str) -> tuple[int, int]:
    start = sum(len(l) + 1 for l in LINES[:line_no]) + LINES[line_no].index(word)
    return start, start + len(word)


def _mention(skill_id, line_no, word, section):
    start, end = _at(line_no, word)
    return {"skill_id": skill_id, "surface": word, "char_start": start, "char_end": end, "section_type": section}


STRUCTURE = {
    "education": [{"school": "某某大学", "degree": "本科", "char_start": 0, "char_end": len(LINES[0])}],
    "work": [],
    "skill_mentions": [_mention(1, 1, "Java", "skills"), _mention(3, 1, "Redis", "skills"),
                       _mention(3, 3, "Redis", "projects"), _mention(9, 1, "Docker", "skills")],
}


def _req(rid, category, content, skill_id=None, req_type="hard", quote=""):
    return {"id": rid, "req_type": req_type, "category": category, "content": content, "quote": quote,
            "skill_id": skill_id, "weight": {"hard": 1.0, "plus": 0.5, "soft": 0.3}[req_type]}


def _match(req, structure=STRUCTURE):
    return match_by_rules(req, structure, TEXT, TODAY)


def test_skill_used_in_experience_is_a_hit_with_the_line_as_evidence():
    item = _match(_req(1, "skill", "熟悉 Redis", skill_id=3))
    assert (item.status, item.matched_by) == ("hit", "dict")
    assert item.evidence_quote == LINES[3] and TEXT[item.char_start:item.char_end] == item.evidence_quote


def test_skill_only_listed_is_partial_and_unknown_skill_is_left_to_the_model():
    item = _match(_req(1, "skill", "熟悉 Docker", skill_id=9))
    assert (item.status, item.evidence_quote) == ("partial", LINES[1]) and "技能清单" in item.reason
    assert _match(_req(2, "skill", "熟悉 Kafka", skill_id=50)) is None        # 词典没扫到 ≠ 不会
    assert _match(_req(3, "skill", "熟悉 JVM 内存模型")) is None               # 词典里没有的技能
    assert _match(_req(4, "other", "良好的沟通能力")) is None


@pytest.mark.parametrize(("content", "status"), [("本科及以上学历", "hit"), ("大专及以上", "hit"), ("硕士及以上学历", "miss")])
def test_education(content, status):
    item = _match(_req(1, "education", content))
    assert (item.status, item.matched_by, item.evidence_quote) == (status, "profile", LINES[0])


def test_education_is_undecided_without_a_degree_on_either_side():
    assert _match(_req(1, "education", "计算机相关专业")) is None
    assert _match(_req(1, "education", "本科及以上"), {**STRUCTURE, "education": [{"degree": None}]}) is None
    assert [degree_level(s) for s in ("博士研究生", "硕士", "Bachelor of Science", "专科", "高中")] == [4, 3, 2, 1, 0]


def test_experience_years_merges_overlaps_and_skips_campus_and_vague_dates():
    work = [{"kind": "work", "start": "2024-01", "end": "2024-12"},
            {"kind": "internship", "start": "2024-07", "end": "2025-06"},            # 与上一段重叠 6 个月
            {"kind": "internship", "start": "2026-03", "end": None, "is_present": True},
            {"kind": "campus", "start": "2020-01", "end": "2023-12"},                # 校园经历不算
            {"kind": "work", "start": "2019", "end": "2020"},                         # 只有年份 → 跳过
            {"kind": "work", "start": None, "end": None}]
    assert experience_years({"work": work}, TODAY) == round((17 + 6) / 12, 1)
    assert experience_years({}, TODAY) == 0


def test_years_requirement():
    structure = {"work": [{"kind": "work", "start": "2024-09", "end": "2026-03"}]}                # 1.5 年
    statuses = [_match(_req(1, "experience", c), structure).status
                for c in ("1 年以上后端开发经验", "3年以上工作经验", "5 年以上经验")]
    assert statuses == ["hit", "partial", "miss"]
    assert "1.5 年" in _match(_req(1, "experience", "3年以上工作经验"), structure).reason
    assert _match(_req(1, "experience", "有高并发项目经验"), structure) is None


def test_score_is_weighted_and_unjudged_requirements_count_as_miss():
    reqs = [_req(1, "skill", "a"), _req(2, "skill", "b"), _req(3, "skill", "c", req_type="plus"),
            _req(4, "education", "d"), _req(5, "other", "e", req_type="soft")]
    items = [MatchItem(1, "hit", "dict", ""), MatchItem(2, "partial", "dict", ""), MatchItem(4, "hit", "profile", "")]
    overall, detail = score_match(reqs, items)
    assert detail == {"skill": 60.0, "education": 100.0, "experience": None, "other": 0.0}
    assert overall == round(100 * (1 + 0.5 + 0 + 1 + 0) / (1 + 1 + 0.5 + 1 + 0.3), 1)
    assert score_match([], []) == (None, dict.fromkeys(("skill", "education", "experience", "other")))
