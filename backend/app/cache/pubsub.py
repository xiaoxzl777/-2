"""后台任务的进度推送：任务往 Redis 频道发事件，SSE 接口订阅后转给浏览器。

进度只是体验上的锦上添花：发布失败只记一条警告，绝不影响任务本身；
前端收不到事件时会退回到轮询资源状态（见 docs/03-api.md 3.3）。
"""
from __future__ import annotations

import json
import logging
import time
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


class Subscription:
    """订阅一个任务的进度频道。用完必须 close（SSE 接口在 finally 里关）。"""

    def __init__(self, task_id: str):
        self._pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        self._pubsub.subscribe(channel(task_id))

    def get(self, timeout: float) -> dict | None:
        """最多等 timeout 秒；返回 {"event", "data"}，没有消息返回 None。Redis 出问题时当作没有消息。"""
        try:
            message = self._pubsub.get_message(timeout=timeout)
            return json.loads(message["data"]) if message else None
        except Exception as e:  # noqa: BLE001
            logger.warning("读取进度频道失败：%s", e)
            time.sleep(timeout)                    # 别让调用方的循环空转
            return None

    def close(self) -> None:
        try:
            self._pubsub.close()
        except Exception:  # noqa: BLE001
            pass


Subscribe = Callable[[str], Subscription]


def get_subscriber() -> Subscribe:
    """FastAPI 依赖；测试里替换成预先排好消息的假订阅。"""
    return Subscription
