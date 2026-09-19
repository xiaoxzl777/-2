"""全局 Redis 连接。缓存、限流、SSE 推送都从这里取。"""
from __future__ import annotations

import redis

from app.config import settings

redis_client: redis.Redis = redis.Redis.from_url(
    settings.REDIS_URL, decode_responses=True, socket_connect_timeout=3
)


def ping() -> bool:
    return bool(redis_client.ping())
