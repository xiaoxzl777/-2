"""模型服务现在能不能用：给登录后页面顶上的横幅（GET /system/llm）。

两个来源：① 问 DeepSeek 的余额接口（GET /user/balance，不花钱）——余额用完 is_available=false、密钥不对 401、连不上抛异常；
② 真正调用模型时碰上同样的错误（llm/client.py 里调 mark_down），横幅马上出来，不用等下一次问余额。
结论在 Redis 里存 1 分钟，所以余额接口 1 分钟最多问一次；恢复后最多 1 分钟横幅自己消失。
这里只是提示：Redis 不通就不存、每次现问；余额接口出了意料之外的状况（比如 500）按能用处理，宁可少报，不让横幅误报。
"""
from __future__ import annotations

import logging

import httpx

from app.cache.redis_client import redis_client
from app.config import settings
from app.llm.registry import http_client

logger = logging.getLogger("app.llm")

KEY = "llm:status"
TTL_SECONDS = 60
_OK = ""                 # Redis 里存空串 = 能用


def unavailable_reason() -> str | None:
    """不可用的原因（排查用，页面上不显示）；None = 能用。"""
    try:
        cached = redis_client.get(KEY)
    except Exception:  # noqa: BLE001
        cached = None
    if cached is not None:
        return cached or None
    reason = _probe()
    if reason:
        logger.warning("模型服务不可用：%s", reason)
    _remember(reason)
    return reason


def mark_down(reason: str) -> None:
    """真正调用时发现服务调不通：先记下来，接下来 1 分钟里打开的页面都会看到横幅。"""
    _remember(reason)


def _remember(reason: str | None) -> None:
    try:
        redis_client.set(KEY, reason or _OK, ex=TTL_SECONDS)
    except Exception as e:  # noqa: BLE001 —— 横幅只是提示，Redis 出问题不能连累模型调用本身
        logger.warning("记录模型服务状态失败：%s", e)


def _probe() -> str | None:
    if not settings.DEEPSEEK_API_KEY:
        return "没有配置 DEEPSEEK_API_KEY"
    try:
        r = http_client().get(f"{settings.DEEPSEEK_BASE_URL.rstrip('/')}/user/balance", timeout=5,
                              headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"})
    except httpx.HTTPError as e:
        return f"连不上模型服务（{type(e).__name__}）"
    if r.status_code in (401, 403):
        return f"密钥无效（{r.status_code}）"
    try:
        available = r.json().get("is_available") if r.status_code == 200 else None
    except ValueError:
        available = None
    if available is None:
        logger.warning("余额接口返回了意料之外的结果（%s），按能用处理", r.status_code)
        return None
    return None if available else "余额不足"
