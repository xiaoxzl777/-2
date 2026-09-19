"""sql/seed.sql 必须与 data/skills_seed.csv 一致。失败时运行：python scripts/dump_seed.py"""
import pytest

from scripts.dump_seed import SEED_PATH, load_skills, render


def test_seed_sql_matches_csv():
    assert SEED_PATH.exists(), "缺少 sql/seed.sql，请运行 python scripts/dump_seed.py"
    assert SEED_PATH.read_text(encoding="utf-8") == render(), (
        "skills_seed.csv 已修改但 seed.sql 未更新，请运行 python scripts/dump_seed.py"
    )


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
