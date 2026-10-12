"""全局 Redis 连接。缓存、限流、SSE 推送都从这里取。

分两个连接池，因为占连接的方式不一样（压测时测出来的，见 docs/08 第 14 章）：
· redis_client   缓存、限流、发布进度这些一问一答的操作：连接都被占着时排队等，不报错。redis-py 默认的连接池
                 到 100 个连接就直接抛 Too many connections——30 个人同时投递、三百来个并行的模型调用一起来占
                 限流名额时就撞上了，分析成片失败。
· pubsub_client  订阅进度频道：每条进度流从头到尾占着一个连接。和上面共用的话，开着的进度流一多，
                 缓存和限流就排不到连接了。
"""
from __future__ import annotations

import redis

from app.config import settings

_OPTIONS = {"decode_responses": True, "socket_connect_timeout": 3}

redis_client: redis.Redis = redis.Redis(connection_pool=redis.BlockingConnectionPool.from_url(
    settings.REDIS_URL, max_connections=50, timeout=20, **_OPTIONS))      # timeout：排队最多等几秒
pubsub_client: redis.Redis = redis.Redis.from_url(settings.REDIS_URL, max_connections=1000, **_OPTIONS)


def ping() -> bool:
    return bool(redis_client.ping())
