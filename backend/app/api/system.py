"""系统接口：健康检查。"""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.cache import redis_client
from app.database import engine

router = APIRouter(tags=["system"])


def _probe(check) -> str:
    try:
        check()
        return "ok"
    except Exception as e:  # noqa: BLE001 —— 健康检查要吞掉一切异常并如实上报
        return f"error: {type(e).__name__}"


def _ping_mysql() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


@router.get("/health")
def health() -> dict:
    """逐项探测依赖。部署出问题时第一个看它。"""
    status = {"mysql": _probe(_ping_mysql), "redis": _probe(redis_client.ping)}
    healthy = all(v == "ok" for v in status.values())
    return {
        "code": 0 if healthy else 50001,
        "message": "success" if healthy else "dependency error",
        "data": {**status, "version": __version__},
    }
