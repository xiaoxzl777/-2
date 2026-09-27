"""种子数据的三处来源必须一致：
data/skills_seed.csv、data/job_templates.json → sql/seed.sql（python scripts/dump_seed.py），
data/job_templates/*.txt → data/job_templates.json（python scripts/build_job_templates.py）。"""
import pytest

from scripts.build_job_templates import load_sources, skill_dict
from scripts.dump_seed import SEED_PATH, load_skills, load_templates, render


def test_seed_sql_matches_sources():
    assert SEED_PATH.exists(), "缺少 sql/seed.sql，请运行 python scripts/dump_seed.py"
    assert SEED_PATH.read_text(encoding="utf-8") == render(), (
        "skills_seed.csv 或 job_templates.json 已修改但 seed.sql 未更新，请运行 python scripts/dump_seed.py"
    )


def test_job_templates_json_matches_txt():
    parsed = [(t["title"], t["raw_text"]) for t in load_templates()]
    assert parsed == [(s["title"], s["raw_text"]) for s in load_sources()], (
        "data/job_templates/ 下的模板原文改过了，请运行 python scripts/build_job_templates.py 再运行 dump_seed.py"
    )


def test_job_templates_are_valid():
    templates, skills = load_templates(), skill_dict()
    assert 5 <= len(templates) <= 8 and len({t["title"] for t in templates}) == len(templates)
    for t in templates:
        reqs = t["requirements"]
        assert [r["id"] for r in reqs] == list(range(1, len(reqs) + 1)), t["title"]
        for r in reqs:
            # 要求项的原文区间相对 raw_text，匹配和结果页都靠它
            assert t["raw_text"][r["char_start"]:r["char_end"]] == r["quote"], (t["title"], r["id"])
            # skill_id 与当前词典一致（词典改了 id 却没重新解析模板时会在这里报出来）
            assert r["skill_id"] == (skills.lookup(r["skill"]) if r["skill"] else None), (t["title"], r["id"])


def test_csv_is_valid_and_reasonably_sized():
    skills = load_skills()
    assert len(skills) >= 100
    names = [s["canonical_name"].lower() for s in skills]
    assert len(names) == len(set(names))


def test_word_owned_by_two_skills_is_rejected(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("canonical_name,category,aliases\nReact,frontend,RN\nReact Native,mobile,rn\n", encoding="utf-8")
    with pytest.raises(ValueError, match="同时属于"):
        load_skills(p)
