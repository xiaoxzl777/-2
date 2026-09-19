"""后台任务的进度推送：任务往 Redis 频道发事件，SSE 接口订阅后转给浏览器。

进度只是体验上的锦上添花：发布失败只记一条警告，绝不影响任务本身；
前端收不到事件时会退回到轮询资源状态（见 docs/03-api.md 3.3）。
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable

from app.cache.redis_client import redis_client

logger = logging.getLogger("app.pubsub")

Publish = Callable[[str, str, dict], None]     # (task_id, event, data)；event ∈ progress / done / error


def channel(task_id: str) -> str:
    return f"task:{task_id}"                   # task_id 形如 "apply:17"


def publish(task_id: str, event: str, data: dict) -> None:
    try:
        redis_client.publish(channel(task_id), json.dumps({"event": event, "data": data}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        logger.warning("进度推送失败（不影响任务）：%s", e)


def get_publisher() -> Publish:
    """FastAPI 依赖；测试里替换成一个收集事件的列表。"""
    return publish
