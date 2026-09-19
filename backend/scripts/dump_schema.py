"""从 app/models.py 生成建表 SQL：python scripts/dump_schema.py

输出 backend/sql/schema.sql，可在 MySQL 客户端里手动执行建库建表。
models.py 是表结构的唯一事实来源；改了模型就重新跑一次本脚本并一起提交
（tests/test_schema_sync.py 会检查两者是否一致）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.dialects import mysql  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

from app.models import MYSQL_POST_DDL, Base  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
DB_NAME = "resume_ai"

HEADER = f"""-- 智能求职辅助系统 建库建表脚本（MySQL 8.0）
-- 本文件由 scripts/dump_schema.py 从 app/models.py 自动生成，请勿手改。
--
-- 手动建表（在全新的库上执行一次；CREATE INDEX 不可重复执行）：
--   mysql -uroot -p < backend/sql/schema.sql
-- （也可以不执行：后端首次启动会自动建库建表，效果相同）

CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `{DB_NAME}`;
"""


def render() -> str:
    dialect = mysql.dialect()
    parts = [HEADER]
    # sorted_tables 按外键依赖排序，保证被引用的表先建
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table, if_not_exists=True).compile(dialect=dialect)).strip()
        parts.append(f"-- {table.name}\n{ddl};")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            parts.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
        parts.append("")
    parts.append("-- MySQL 专有补充（幂等）")
    parts.extend(ddl + ";" for ddl in MYSQL_POST_DDL)
    return "\n".join(parts).replace("\t", "  ") + "\n"


def main() -> None:
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(render(), encoding="utf-8", newline="\n")
    print(f"已生成 {SCHEMA_PATH}（{len(Base.metadata.tables)} 张表）")


if __name__ == "__main__":
    main()
