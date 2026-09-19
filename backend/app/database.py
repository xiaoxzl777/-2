"""数据库连接：同步 SQLAlchemy 2.0 + PyMySQL。

选择同步栈的原因：单人毕设、单进程部署，FastAPI 的 def 端点自动在线程池执行，
BackgroundTasks 与 LangGraph 也都走同步 API，避免 async 驱动带来的额外复杂度。

表结构不由代码建立：在 MySQL 中手动执行 backend/sql/schema.sql。
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
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


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个 Session，请求结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
