"""按服务商限流：固定窗口计数器（每分钟一个桶）。

并行审查会同时发出十几个请求，超过服务商的 RPM 会被拒绝并浪费重试；
这里在发请求前先占一个名额，名额用完就等到下一分钟。
"""
from __future__ import annotations

import time

from app.cache.redis_client import redis_client

WINDOW_SECONDS = 60
MAX_WAIT_SECONDS = 120


class RateLimitTimeout(Exception):
    pass


def acquire(provider: str, limit_per_minute: int) -> None:
    """阻塞直到拿到一个名额。"""
    deadline = time.monotonic() + MAX_WAIT_SECONDS
    while True:
        now = time.time()
        key = f"ratelimit:{provider}:{int(now // WINDOW_SECONDS)}"
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, WINDOW_SECONDS * 2)
        if count <= limit_per_minute:
            return
        if time.monotonic() > deadline:
            raise RateLimitTimeout(f"{provider} 限流等待超时")
        time.sleep(WINDOW_SECONDS - now % WINDOW_SECONDS + 0.05)  # 睡到下一个窗口开始
