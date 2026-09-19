"""全系统调用大模型的唯一出口（系统不变量④）。

每次调用固定五步：
  ① 渲染 prompt，算缓存 key            ② 缓存命中 → 记一行审计（cache_hit）→ 返回
  ③ 限流占位                            ④ 调模型，取 token 用量 / 模型指纹，按单价估算成本
  ⑤ 写缓存 + 记审计 → 返回 LLMResult

结构化输出：让模型以 JSON 模式作答，再用 Pydantic 校验。解析失败**不抛异常**，
而是放进 LLMResult.parse_error，由调用方带着错误原因重试——与"引用定位失败"走同一条重试路径。

领域层（parser / diagnose / matching / interview）只依赖这里的 LLMClient 接口，
测试时注入假的模型工厂，不需要网络也不需要 Redis / MySQL。
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.cache import llm_cache, ratelimit
from app.config import settings
from app.llm import audit, registry

logger = logging.getLogger("app.llm")

Message = tuple[str, str]  # (role, content)；role ∈ system / user / assistant
T = TypeVar("T", bound=BaseModel)

# 评测批次号：设置后本次调用绕过缓存，并在审计里带上 run_id（实验要测真实行为，不能命中缓存）
current_run_id: ContextVar[str | None] = ContextVar("current_run_id", default=None)

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


class LLMError(Exception):
    """模型调用失败（网络、鉴权、超时等，已含客户端内置的重试）。"""


class Cache(Protocol):
    def get(self, key: str) -> dict | None: ...
    def put(self, key: str, value: dict) -> None: ...


@dataclass(slots=True)
class LLMResult:
    text: str
    parsed: Any | None            # schema 的实例；没传 schema 或解析失败时为 None
    parse_error: str | None
    token_input: int
    token_output: int
    cost: float                   # 元；缓存命中为 0
    cache_hit: bool
    model: str
    model_version: str | None     # 服务商返回的 system_fingerprint
    latency_ms: int


def parse_json(text: str, schema: type[T]) -> tuple[T | None, str | None]:
    """返回 (对象, None) 或 (None, 错误原因)。错误原因会原样反馈给模型用于重试。"""
    cleaned = _CODE_FENCE.sub("", text.strip())
    if not cleaned:
        return None, "模型返回了空内容"
    try:
        return schema.model_validate(json.loads(cleaned)), None
    except json.JSONDecodeError as e:
        return None, f"不是合法的 JSON：{e.msg}（第 {e.lineno} 行）"
    except ValidationError as e:
        first = e.errors()[0]
        return None, f"字段不符合要求：{'.'.join(map(str, first['loc']))} {first['msg']}"


class LLMClient:
    def __init__(
        self,
        chat_factory: Callable[[str, float], Any] = registry.get_chat_model,
        cache: Cache = llm_cache,
        acquire: Callable[[str, int], None] = ratelimit.acquire,
        write_audit: Callable[[dict], None] = audit.write_llm_call,
    ):
        self._chat_factory = chat_factory
        self._cache = cache
        self._acquire = acquire
        self._write_audit = write_audit

    def invoke(
        self,
        scene: str,
        messages: Sequence[Message],
        *,
        prompt_version: str,
        schema: type[BaseModel] | None = None,
        ref: tuple[str, int] | None = None,     # (ref_type, ref_id)，如 ("diagnosis", 88)
        model: str | None = None,
        temperature: float = 0.0,
        use_cache: bool = True,
    ) -> LLMResult:
        model = model or settings.CHAT_MODEL
        rendered = json.dumps(
            {"messages": list(messages), "schema": schema.__name__ if schema else None, "temperature": temperature},
            ensure_ascii=False, sort_keys=True,
        )
        if schema is not None and "json" not in rendered.lower():
            raise ValueError("JSON 模式要求 prompt 中出现 'json' 字样（DeepSeek 的限制），请在 prompt 里给出 JSON 示例")

        run_id = current_run_id.get()
        key = llm_cache.make_key(scene, model, prompt_version, rendered)
        base_record = {
            "scene": scene, "ref_type": ref[0] if ref else None, "ref_id": ref[1] if ref else None,
            "provider": registry.PROVIDERS.get(model), "model_name": model,
            "prompt_version": prompt_version, "run_id": run_id,
        }

        cacheable = use_cache and run_id is None
        if cacheable and (hit := self._cache.get(key)) is not None:
            parsed, parse_error = parse_json(hit["text"], schema) if schema else (None, None)
            self._write_audit({**base_record, "model_version": hit.get("model_version"), "cache_hit": True,
                               "latency_ms": 0})
            return LLMResult(hit["text"], parsed, parse_error, 0, 0, 0.0, True, model, hit.get("model_version"), 0)

        self._acquire(registry.PROVIDERS.get(model, model), settings.DEEPSEEK_RPM)
        started = time.perf_counter()
        try:
            chat = self._chat_factory(model, temperature)
            if schema is not None:
                chat = chat.bind(response_format={"type": "json_object"})
            reply = chat.invoke(list(messages))
        except Exception as e:
            latency = int((time.perf_counter() - started) * 1000)
            self._write_audit({**base_record, "success": False, "latency_ms": latency,
                               "error_msg": f"{type(e).__name__}: {e}"[:500]})
            raise LLMError(f"{scene} 调用 {model} 失败：{type(e).__name__}") from e
        latency = int((time.perf_counter() - started) * 1000)

        text = reply.content if isinstance(reply.content, str) else str(reply.content)
        usage = reply.usage_metadata or {}
        token_in, token_out = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        model_version = (reply.response_metadata or {}).get("system_fingerprint")
        cost = registry.estimate_cost(model, token_in, token_out)
        parsed, parse_error = parse_json(text, schema) if schema else (None, None)

        # 空内容 / 解析失败不进缓存：那往往是偶发问题，缓存住会让它持续 7 天
        if cacheable and text.strip() and parse_error is None:
            self._cache.put(key, {"text": text, "model_version": model_version})
        self._write_audit({**base_record, "model_version": model_version, "token_input": token_in,
                           "token_output": token_out, "cost": cost, "latency_ms": latency})
        return LLMResult(text, parsed, parse_error, token_in, token_out, cost, False, model, model_version, latency)


_default_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
