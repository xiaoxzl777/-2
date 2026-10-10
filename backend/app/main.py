"""FastAPI 入口。启动：uvicorn app.main:app --reload（在 backend/ 目录下）

必须单进程运行（--workers 1）：BackgroundTasks 在接收请求的进程内执行，
启动清理也依赖"启动那一刻库里的 running 必然是上次进程留下的死任务"这一前提。
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app import __version__
from app.api import api_router
from app.cache import redis_client
from app.config import settings
from app.database import SessionLocal, engine
from app.errors import register_error_handlers
from app.models import Base

logger = logging.getLogger("app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")

# 上次进程异常退出时卡在"进行中"的任务 → 标为失败，前端据 interrupted 提示用户重试
_CLEANUP_SQL = {
    "resumes": "UPDATE resumes SET parse_status='failed', parse_error='interrupted' WHERE parse_status IN ('pending','parsing')",
    "diagnoses": "UPDATE diagnoses SET status='failed', error_msg='interrupted' WHERE status IN ('pending','running')",
    "match_reports": "UPDATE match_reports SET status='failed', error_msg='interrupted' WHERE status IN ('pending','running')",
}
IDLE_SWEEP_SECONDS = 3600  # 多久扫一次很久没动静的面试（"多久算放弃"是 INTERVIEW_IDLE_HOURS）


def check_database() -> None:
    """表结构由 backend/sql/schema.sql 手动建立，服务只检查、不建表。"""
    try:
        existing = set(inspect(engine).get_table_names())
    except Exception as e:
        raise RuntimeError(
            "MySQL 连接失败。请检查：MySQL 是否启动、.env 的 DATABASE_URL 是否正确、"
            f"是否已执行 backend/sql/schema.sql 建库：{e}"
        ) from e
    missing = sorted(set(Base.metadata.tables) - existing)
    if missing:
        raise RuntimeError(f"数据库缺少表 {missing}。请在 MySQL 中执行 backend/sql/schema.sql。")


def check_redis() -> None:
    try:
        redis_client.ping()
    except Exception as e:
        raise RuntimeError(
            f"Redis 连接失败（{settings.REDIS_URL}）。请先启动本机 Redis，或执行 docker compose up -d redis：{e}"
        ) from e


def cleanup_interrupted_tasks() -> dict[str, int]:
    with engine.begin() as conn:
        cleaned = {table: conn.execute(text(sql)).rowcount for table, sql in _CLEANUP_SQL.items()}
    # 面试不一样：停在"等回答"是正常状态，不算中断。只有很久没动静的才按已答的题出报告、标成放弃
    cleaned["interview_sessions"] = sweep_idle_interviews()
    return cleaned


def sweep_idle_interviews() -> int:
    from app.graphs.checkpoint import get_checkpointer
    from app.retrieval.context_store import get_context_store
    from app.services import interview_service
    return interview_service.cleanup_idle(SessionLocal, get_checkpointer(), get_context_store)


def load_admin_settings() -> None:
    """管理员账号没有就建一个；管理端选了哪家模型，读进内存（llm/provider.py）。"""
    from app.llm import provider
    from app.services import admin_service
    with SessionLocal() as db:
        admin_service.ensure_admin(db)
        current = provider.load(db)
    logger.info("对话模型：%s · %s（%s）", current.name, current.model, "管理端配置" if current.id else ".env")


async def sweep_forever(interval: float) -> None:
    """服务一直开着时也定时给很久没动静的面试收尾。原来只在启动时清一次，长期不重启就一直显示「进行中」"""
    while True:
        await asyncio.sleep(interval)
        try:
            if n := await asyncio.to_thread(sweep_idle_interviews):
                logger.info("收尾了 %d 场很久没动静的面试", n)
        except Exception:                                   # noqa: BLE001  这次失败就等下一轮，循环不能停
            logger.exception("清理很久没动静的面试失败")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 依赖有问题就直接退出，不带病运行
    check_database()
    check_redis()
    if settings.JWT_SECRET.startswith("change-me"):
        logger.warning("JWT_SECRET 仍是示例值，部署前请在 .env 中改成随机长字符串")
    cleaned = cleanup_interrupted_tasks()
    load_admin_settings()
    logger.info("启动完成：MySQL %d 张表，Redis ok，清理中断任务 %s", len(Base.metadata.tables), cleaned)
    sweeper = asyncio.create_task(sweep_forever(IDLE_SWEEP_SECONDS))
    yield
    sweeper.cancel()
    engine.dispose()


app = FastAPI(title="智能求职辅助系统", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vite 开发服务器
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_error_handlers(app)
app.include_router(api_router)
