"""FastAPI 入口。启动：uvicorn app.main:app --reload（在 backend/ 目录下）

必须单进程运行（--workers 1）：BackgroundTasks 在接收请求的进程内执行，
启动清理也依赖"启动那一刻库里的 running 必然是上次进程留下的死任务"这一前提。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app import __version__
from app.cache import redis_client as rc
from app.config import settings
from app.database import engine
from app.models import Base

logger = logging.getLogger("app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")

API_PREFIX = "/api/v1"

# 上次进程异常退出时卡在"进行中"的任务 → 标为失败，前端据 interrupted 提示用户重试
_CLEANUP_SQL = {
    "resumes": "UPDATE resumes SET parse_status='failed', parse_error='interrupted' WHERE parse_status='parsing'",
    "diagnoses": "UPDATE diagnoses SET status='failed', error_msg='interrupted' WHERE status='running'",
    "match_reports": "UPDATE match_reports SET status='failed', error_msg='interrupted' WHERE status='running'",
}


def cleanup_interrupted_tasks() -> dict[str, int]:
    counts: dict[str, int] = {}
    with engine.begin() as conn:
        for table, sql in _CLEANUP_SQL.items():
            counts[table] = conn.execute(text(sql)).rowcount
    return counts


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 依赖连不上就直接退出，不带病运行
    # 表结构由 backend/sql/schema.sql 手动建立，服务只检查、不建表
    try:
        tables = set(inspect(engine).get_table_names())
    except Exception as e:
        raise RuntimeError(
            "MySQL 连接失败。请检查：MySQL 是否启动、.env 的 DATABASE_URL 是否正确、"
            f"是否已执行 backend/sql/schema.sql 建库：{e}"
        ) from e
    missing = sorted(set(Base.metadata.tables) - tables)
    if missing:
        raise RuntimeError(f"数据库缺少表 {missing}。请在 MySQL 中执行 backend/sql/schema.sql。")
    try:
        rc.ping()
    except Exception as e:
        raise RuntimeError(
            f"Redis 连接失败（{settings.REDIS_URL}）。请先启动本机 Redis，或执行 docker compose up -d redis：{e}"
        ) from e

    cleaned = cleanup_interrupted_tasks()
    logger.info("启动完成：MySQL %d 张表，Redis ok，清理中断任务 %s", len(tables), cleaned)
    yield
    engine.dispose()


app = FastAPI(title="智能求职辅助系统", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vite 开发服务器
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(f"{API_PREFIX}/health", tags=["system"])
def health() -> dict:
    """逐项探测依赖。部署出问题时第一个看它。"""
    status: dict[str, str] = {}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status["mysql"] = "ok"
    except Exception as e:  # noqa: BLE001
        status["mysql"] = f"error: {type(e).__name__}"
    try:
        rc.ping()
        status["redis"] = "ok"
    except Exception as e:  # noqa: BLE001
        status["redis"] = f"error: {type(e).__name__}"

    ok = all(v == "ok" for v in status.values())
    return {"code": 0 if ok else 50001, "message": "success" if ok else "dependency error",
            "data": {**status, "version": __version__}}
