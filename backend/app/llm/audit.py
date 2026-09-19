"""调用审计：每一次模型调用（含缓存命中）记一行 llm_calls，用于成本统计与实验复核。"""
from __future__ import annotations

import logging

from app.database import SessionLocal
from app.models import LlmCall

logger = logging.getLogger("app.llm")


def write_llm_call(record: dict) -> None:
    """审计失败不能影响业务：只记日志，不抛出。"""
    try:
        with SessionLocal() as db:
            db.add(LlmCall(**record))
            db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("llm_calls 写入失败")
