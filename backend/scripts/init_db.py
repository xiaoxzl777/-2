"""建库建表：python scripts/init_db.py [--drop]

服务启动时会自动建库建表（app.database.ensure_database），平时不需要手动跑。
本脚本用于：不启动服务只建表；或 --drop 在开发期表结构变更后重建（会清空数据）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.database import engine, ensure_database  # noqa: E402
from app.models import Base  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drop", action="store_true", help="先删除全部表（清空数据）")
    args = parser.parse_args()

    ensure_database()  # 先保证库存在，drop 才有地方可连
    if args.drop:
        Base.metadata.drop_all(engine)
        print("已删除全部表")
    tables = ensure_database()

    print(f"数据库 {engine.url.database}（{settings.APP_ENV}）：{len(tables)} 张表")
    for t in tables:
        print(f"  - {t}")


if __name__ == "__main__":
    main()
