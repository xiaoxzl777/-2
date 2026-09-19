"""sql/schema.sql 必须与 app/models.py 一致。失败时运行：python scripts/dump_schema.py"""
from scripts.dump_schema import SCHEMA_PATH, render


def test_schema_sql_matches_models():
    assert SCHEMA_PATH.exists(), "缺少 sql/schema.sql，请运行 python scripts/dump_schema.py"
    assert SCHEMA_PATH.read_text(encoding="utf-8") == render(), (
        "models.py 已修改但 schema.sql 未更新，请运行 python scripts/dump_schema.py"
    )
