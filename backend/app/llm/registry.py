"""把「现在用哪一家」（llm/provider.py）变成 LangChain 的聊天模型，并按它的单价估算花费。"""
from __future__ import annotations

from functools import cache

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI

from app.config import settings
from app.llm import provider
from app.llm.provider import Provider


@cache
def http_client() -> httpx.Client:
    # 全进程共用一个（线程安全；llm/status.py 问余额也用它）：每次新建要重新加载证书（实测约 0.23 秒）、重新握手，诊断时十几个并行请求各付一次。
    # 本机若配了 HTTP(S)_PROXY，国内模型服务走代理反而慢数倍；默认直连
    return httpx.Client(trust_env=settings.LLM_USE_SYSTEM_PROXY, timeout=settings.LLM_TIMEOUT_SECONDS)


def build_chat_model(p: Provider, temperature: float, *, max_retries: int = 3, timeout: float | None = None) -> BaseChatModel:
    """DeepSeek 用它自己的封装（一直用的那个，行为不变）；别家国内主流都提供 OpenAI 兼容接口，统一用 ChatOpenAI。"""
    common = dict(
        model=p.model,
        api_key=p.api_key,
        temperature=temperature,
        max_retries=max_retries,            # openai 客户端内置指数退避（NFR-3）
        stream_usage=True,                  # 流式调用时最后一个分块带 token 用量，记账要用
        timeout=timeout or settings.LLM_TIMEOUT_SECONDS,
        http_client=http_client(),
    )
    if p.is_deepseek:
        return ChatDeepSeek(api_base=p.base_url, **common)
    return ChatOpenAI(base_url=p.base_url, **common)


def get_chat_model(name: str, temperature: float) -> BaseChatModel:
    p = provider.current()
    if name != p.model:
        raise ValueError(f"未注册的模型：{name}（现在用的是 {p.model}）")
    return build_chat_model(p, temperature)


def available_models() -> list[str]:
    """接口里 model 参数能填的值：只有现在启用的那一个。"""
    return [provider.current().model]


def provider_of(model: str) -> str:
    """模型名 → 服务商，用于限流分桶与审计。"""
    p = provider.current()
    return p.kind if model == p.model else model


def estimate_cost(model: str, token_input: int, token_output: int) -> float:
    p = provider.current()
    price_in, price_out = ((p.price_in, p.price_out) if model == p.model
                           else provider.ENV_PRICES.get(model, provider.DEFAULT_PRICE))
    return round((token_input * price_in + token_output * price_out) / 1_000_000, 6)
