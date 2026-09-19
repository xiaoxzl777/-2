"""建库建表：python scripts/init_db.py [--drop]

1. 连到 MySQL 服务器（不带库名），库不存在则创建（utf8mb4）。
2. 按 app/models.py 建出 11 张表；已存在的表不动。
--drop 先删掉全部表再建（开发期表结构变更时用，会清空数据）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.config import settings  # noqa: E402
from app.models import Base  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drop", action="store_true", help="先删除全部表（清空数据）")
    args = parser.parse_args()

    url = make_url(settings.DATABASE_URL)
    db_name = url.database

    server = create_engine(url.set(database=None))
    with server.connect() as conn:
        conn.execute(
            text(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        )
        conn.commit()
    server.dispose()

    engine = create_engine(url)
    if args.drop:
        Base.metadata.drop_all(engine)
        print("已删除全部表")
    Base.metadata.create_all(engine)

    tables = sorted(inspect(engine).get_table_names())
    print(f"数据库 {db_name}：{len(tables)} 张表")
    for t in tables:
        print(f"  - {t}")


if __name__ == "__main__":
    main()
