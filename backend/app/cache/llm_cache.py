"""LLM 结果缓存：同样的输入不重复付费。

这是 Redis 各项职责里唯一做了容错的一处：缓存读写失败只记一条警告、按未命中处理，
因为它保护的是付费调用——缓存坏了不该让整个诊断失败。
"""
from __future__ import annotations

import hashlib
import json
import logging

from app.cache.redis_client import redis_client
from app.config import settings

logger = logging.getLogger("app.llm")


def make_key(scene: str, model: str, prompt_version: str, rendered: str) -> str:
    """key 含整段渲染后的 prompt 的哈希：同一段经历换了目标岗位或规则结果，就不会命中旧答案。"""
    digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    return f"llm:{scene}:{model}:{prompt_version}:{digest}"


def get(key: str) -> dict | None:
    try:
        raw = redis_client.get(key)
        return json.loads(raw) if raw else None
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 缓存读取失败，按未命中处理：%s", e)
        return None


def put(key: str, value: dict) -> None:
    try:
        redis_client.set(key, json.dumps(value, ensure_ascii=False), ex=settings.LLM_CACHE_TTL_SECONDS)
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 缓存写入失败：%s", e)
