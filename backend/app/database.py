"""数据库连接：同步 SQLAlchemy 2.0 + PyMySQL。

选择同步栈的原因：单人毕设、单进程部署，FastAPI 的 def 端点自动在线程池执行，
BackgroundTasks 与 LangGraph 也都走同步 API，避免 async 驱动带来的额外复杂度。
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,      # MySQL 空闲连接被服务端断开时自动重连
    pool_recycle=3600,
    pool_size=5,
    max_overflow=10,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ensure_database() -> list[str]:
    """库不存在则创建（utf8mb4），再按 models 建出缺失的表；已存在的表不动。返回当前全部表名。

    服务启动与 scripts/init_db.py 共用：新电脑拉下代码后无需手动建库建表。
    """
    from app.models import MYSQL_POST_DDL, Base  # 延迟导入，避免循环依赖

    url = make_url(settings.DATABASE_URL)
    # 注意：URL.set(database=None) 表示"不修改"，要用空串才能去掉库名
    server = create_engine(url.set(database=""))
    try:
        with server.connect() as conn:
            conn.execute(
                text(f"CREATE DATABASE IF NOT EXISTS `{url.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            )
            conn.commit()
    finally:
        server.dispose()

    Base.metadata.create_all(engine)
    if engine.dialect.name == "mysql":
        with engine.begin() as conn:
            for ddl in MYSQL_POST_DDL:
                conn.execute(text(ddl))
    return sorted(inspect(engine).get_table_names())


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个 Session，请求结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
