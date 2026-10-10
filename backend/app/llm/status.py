"""模型服务现在能不能用：给登录后页面顶上的横幅（GET /system/llm）。

两个来源：① 问现在用的那一家（llm/provider.py），不花钱。DeepSeek 有余额接口（GET /user/balance）——余额用完 is_available=false、
密钥不对 401、连不上抛异常；别家没有统一的余额接口，只问一下模型列表（GET /models）：看得出密钥对不对、连不连得上，看不出余额；
② 真正调用模型时碰上同样的错误（llm/client.py 里调 mark_down），横幅马上出来，不用等下一次问余额。
结论在 Redis 里存 1 分钟，所以余额接口 1 分钟最多问一次；恢复后最多 1 分钟横幅自己消失。
这里只是提示：Redis 不通就不存、每次现问；余额接口出了意料之外的状况（比如 500）按能用处理，宁可少报，不让横幅误报。
"""
from __future__ import annotations

import logging

import httpx

from app.cache.redis_client import redis_client
from app.llm import provider
from app.llm.provider import Provider
from app.llm.registry import http_client

logger = logging.getLogger("app.llm")

KEY = "llm:status"
TTL_SECONDS = 60
PROBE_TRIES = 2          # 连不上时再试一次：偶尔一次网络抖动（10-09 实测碰上过 ConnectTimeout）不该让横幅误报一分钟，真正的调用本来也会重试
PROBE_TIMEOUT = 10       # 余额接口有时要 3–5 秒才返回
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


def forget() -> None:
    """换了 Key 或供应商：以前记的结论作废，下一次现问。"""
    try:
        redis_client.delete(KEY)
    except Exception as e:  # noqa: BLE001
        logger.warning("清掉模型服务状态失败：%s", e)


def _probe() -> str | None:
    return check(provider.current())[0]


def check(p: Provider) -> tuple[str | None, str | None]:
    """现问一次这一家，不走缓存。返回 (不可用的原因, 余额)；余额只有 DeepSeek 查得到。管理端的「模型设置」页也用它。"""
    if not p.api_key:
        return "没有配置 API Key", None
    path = "/user/balance" if p.is_deepseek else "/models"
    for attempt in range(PROBE_TRIES):
        try:
            r = http_client().get(f"{p.base_url.rstrip('/')}{path}", timeout=PROBE_TIMEOUT,
                                  headers={"Authorization": f"Bearer {p.api_key}"})
            break
        except httpx.HTTPError as e:
            if attempt == PROBE_TRIES - 1:
                return f"连不上模型服务（{type(e).__name__}）", None
    if r.status_code in (401, 403):
        return f"密钥无效（{r.status_code}）", None
    if not p.is_deepseek:
        return None, None               # 模型列表接口各家不完全一样：别的状态码都按能用处理，真调不通时由 mark_down 兜着
    try:
        body = r.json() if r.status_code == 200 else {}
    except ValueError:
        body = {}
    available = body.get("is_available") if isinstance(body, dict) else None
    if available is None:
        logger.warning("余额接口返回了意料之外的结果（%s），按能用处理", r.status_code)
        return None, None
    return (None if available else "余额不足"), _balance_text(body)


def ping(base_url: str, api_key: str) -> str | None:
    """检索那一家现在能不能用：只问模型列表，不花钱。返回不可用的原因；None = 能用。"""
    return check(Provider(None, "custom", "", base_url, "", api_key, 0.0, 0.0))[0]


def _balance_text(body: dict) -> str | None:
    infos = body.get("balance_infos") or []
    if not infos:
        return None
    info = next((i for i in infos if i.get("currency") == "CNY"), infos[0])
    sign = {"CNY": "¥", "USD": "$"}.get(info.get("currency"), "")
    return f"{sign}{info.get('total_balance')}"
