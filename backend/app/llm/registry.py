"""模型注册表：名字 → LangChain 聊天模型。换模型 / 做模型对比实验只改这里。"""
from __future__ import annotations

from collections.abc import Callable

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_deepseek import ChatDeepSeek

from app.config import settings

# 元 / 百万 token（输入, 输出）。仅用于成本估算与熔断，实际以各平台账单为准。
PRICES: dict[str, tuple[float, float]] = {
    "deepseek-chat": (4.0, 12.0),
}
DEFAULT_PRICE = (4.0, 12.0)

# 模型名 → 服务商，用于限流分桶与审计
PROVIDERS: dict[str, str] = {"deepseek-chat": "deepseek"}


def _http_client() -> httpx.Client:
    # 本机若配了 HTTP(S)_PROXY，国内模型服务走代理反而慢数倍；默认直连
    return httpx.Client(trust_env=settings.LLM_USE_SYSTEM_PROXY, timeout=settings.LLM_TIMEOUT_SECONDS)


def _deepseek(temperature: float) -> BaseChatModel:
    return ChatDeepSeek(
        model="deepseek-chat",
        api_key=settings.DEEPSEEK_API_KEY,
        api_base=settings.DEEPSEEK_BASE_URL,
        temperature=temperature,
        max_retries=3,                      # openai 客户端内置指数退避（NFR-3）
        timeout=settings.LLM_TIMEOUT_SECONDS,
        http_client=_http_client(),
    )


MODEL_REGISTRY: dict[str, Callable[[float], BaseChatModel]] = {
    "deepseek-chat": _deepseek,
}


def get_chat_model(name: str, temperature: float) -> BaseChatModel:
    try:
        return MODEL_REGISTRY[name](temperature)
    except KeyError:
        raise ValueError(f"未注册的模型：{name}（可用：{sorted(MODEL_REGISTRY)}）") from None


def estimate_cost(model: str, token_input: int, token_output: int) -> float:
    price_in, price_out = PRICES.get(model, DEFAULT_PRICE)
    return round((token_input * price_in + token_output * price_out) / 1_000_000, 6)
