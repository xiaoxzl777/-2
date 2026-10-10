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
import re
import time
from collections.abc import Callable, Iterator, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

import openai
from pydantic import BaseModel, ValidationError

from app.cache import llm_cache, ratelimit
from app.config import settings
from app.llm import audit, prompts, provider, registry
from app.llm import status as llm_status

Message = tuple[str, str]  # (role, content)；role ∈ system / user / assistant
T = TypeVar("T", bound=BaseModel)

# 评测批次号：设置后本次调用绕过缓存，并在审计里带上 run_id（实验要测真实行为，不能命中缓存）
current_run_id: ContextVar[str | None] = ContextVar("current_run_id", default=None)

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


# 模型服务调不通时给用户看的话：马上重试没用、得等服务恢复，所以单独说明原因，不和别的失败一样说"调用大模型失败"
LLM_DOWN = "模型服务暂时不可用，请稍后再试"


class LLMError(Exception):
    """模型调用失败（网络、鉴权、超时等，已含客户端内置的重试）。

    unavailable：模型服务调不通的原因（余额不足、密钥无效、连不上……），排查用；其余失败（请求本身的问题等）为 None。
    """

    def __init__(self, message: str, unavailable: str | None = None):
        super().__init__(message)
        self.unavailable = unavailable


def unavailable_reason(e: Exception) -> str | None:
    """服务商返回的错误里，哪些算"模型服务暂时不可用"。"""
    if isinstance(e, openai.APIStatusError):
        code = e.status_code
        if code == 402:
            return "余额不足（402）"
        if code in (401, 403):
            return f"密钥无效（{code}）"
        if code == 429 or code >= 500:
            return f"服务繁忙（{code}）"
        return None
    if isinstance(e, openai.APIConnectionError):     # 超时也是它的子类
        return f"连不上模型服务（{type(e).__name__}）"
    return None


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
        mark_down: Callable[[str], None] = llm_status.mark_down,
    ):
        self._chat_factory = chat_factory
        self._cache = cache
        self._acquire = acquire
        self._write_audit = write_audit
        self._mark_down = mark_down

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
        model = model or provider.current().model
        rendered, key, base_record = self._prepare(scene, messages, prompt_version, schema, ref, model, temperature)
        if schema is not None and "json" not in rendered.lower():
            raise ValueError("JSON 模式要求 prompt 中出现 'json' 字样（DeepSeek 的限制），请在 prompt 里给出 JSON 示例")

        cacheable = use_cache and base_record["run_id"] is None
        if cacheable and (hit := self._cache.get(key)) is not None:
            parsed, parse_error = parse_json(hit["text"], schema) if schema else (None, None)
            self._write_audit({**base_record, "model_version": hit.get("model_version"), "cache_hit": True,
                               "latency_ms": 0})
            return LLMResult(hit["text"], parsed, parse_error, 0, 0, 0.0, True, model, hit.get("model_version"), 0)

        self._take_slot(model, base_record)
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
            raise self._failure(scene, model, e) from e
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

    def stream(
        self,
        scene: str,
        messages: Sequence[Message],
        *,
        prompt_version: str,
        ref: tuple[str, int] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        use_cache: bool = True,
        stats: dict | None = None,
    ) -> Iterator[str]:
        """流式调用：模型每吐一段文字就产出一段，给要"边生成边显示"的场景用（纯文本，不做结构化解析）。

        同样的五步：缓存命中时一次产出全文；限流；调用；写缓存；记账（token 用量来自最后一个分块）。
        中途失败抛 LLMError，已经产出的部分由调用方决定怎么处理；调用方提前关闭生成器也记一行失败，费用照记不漏。
        生成器没有返回值，要知道这次花了多少钱（面试按单场成本封顶）就传一个 stats 字典，结束时填进 cost / token。
        """
        model = model or provider.current().model
        _, key, base_record = self._prepare(scene, messages, prompt_version, None, ref, model, temperature)
        cacheable = use_cache and base_record["run_id"] is None
        if cacheable and (hit := self._cache.get(key)) is not None:
            self._write_audit({**base_record, "model_version": hit.get("model_version"), "cache_hit": True,
                               "latency_ms": 0})
            if stats is not None:
                stats.update(cost=0.0, token_input=0, token_output=0, cache_hit=True)
            yield hit["text"]
            return

        self._take_slot(model, base_record)
        started = time.perf_counter()
        text, usage, model_version = "", {}, None

        def failed(reason: str) -> dict:
            return {**base_record, "success": False, "latency_ms": int((time.perf_counter() - started) * 1000),
                    "error_msg": reason[:500]}

        try:
            for chunk in self._chat_factory(model, temperature).stream(list(messages)):
                usage = chunk.usage_metadata or usage
                model_version = (chunk.response_metadata or {}).get("system_fingerprint") or model_version
                piece = chunk.content if isinstance(chunk.content, str) else ""
                if piece:
                    text += piece
                    yield piece
        except GeneratorExit:
            self._write_audit(failed("调用方提前结束了流式读取"))
            raise
        except Exception as e:
            self._write_audit(failed(f"{type(e).__name__}: {e}"))
            raise self._failure(scene, model, e) from e

        token_in, token_out = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        cost = registry.estimate_cost(model, token_in, token_out)
        if cacheable and text.strip():
            self._cache.put(key, {"text": text, "model_version": model_version})
        self._write_audit({**base_record, "model_version": model_version, "token_input": token_in,
                           "token_output": token_out, "cost": cost,
                           "latency_ms": int((time.perf_counter() - started) * 1000)})
        if stats is not None:
            stats.update(cost=cost, token_input=token_in, token_output=token_out, cache_hit=False)

    def _failure(self, scene: str, model: str, e: Exception) -> LLMError:
        """调用失败转成 LLMError；是服务调不通的，顺手记下来，页面顶上的横幅马上就能出来。"""
        reason = unavailable_reason(e)
        if reason:
            self._mark_down(reason)
        return LLMError(f"{scene} 调用 {model} 失败：{type(e).__name__}", unavailable=reason)

    def _take_slot(self, model: str, base_record: dict) -> None:
        """限流占位。Redis 不通、排队超时也按调用失败处理：调用方的降级逻辑只认 LLMError。"""
        try:
            self._acquire(registry.provider_of(model), settings.DEEPSEEK_RPM)
        except Exception as e:
            self._write_audit({**base_record, "success": False, "latency_ms": 0,
                               "error_msg": f"限流占位失败：{type(e).__name__}: {e}"[:500]})
            raise LLMError(f"{base_record['scene']} 限流占位失败：{type(e).__name__}") from e

    @staticmethod
    def _prepare(scene: str, messages: Sequence[Message], prompt_version: str, schema: type[BaseModel] | None,
                 ref: tuple[str, int] | None, model: str, temperature: float) -> tuple[str, str, dict]:
        """渲染 prompt、算缓存 key、拼审计记录的公共部分。评测批次号（run_id）也在这里取。"""
        rendered = json.dumps(
            {"messages": list(messages), "schema": schema.__name__ if schema else None, "temperature": temperature},
            ensure_ascii=False, sort_keys=True,
        )
        key = llm_cache.make_key(scene, model, prompt_version, rendered)
        base_record = {
            "scene": scene, "ref_type": ref[0] if ref else None, "ref_id": ref[1] if ref else None,
            "provider": registry.provider_of(model), "model_name": model,
            "prompt_version": prompt_version, "run_id": current_run_id.get(),
        }
        return rendered, key, base_record


def invoke_json(llm: LLMClient, scene: str, messages: Sequence[Message], *, schema: type[T],
                prompt_version: str, **kwargs: Any) -> tuple[T | None, float, str | None]:
    """要求 JSON 输出的一次调用：不合格时把上一次的输出和原因发回去，重试一次。

    返回 (解析结果, 两次加起来的花费, 最后一次的错误)；两次都不合格时解析结果为 None。
    重试前还要做别的校验（面试定话题核对编号、评分核对证据、诊断核对引用）的地方自己写循环，不用它。
    """
    cost = 0.0
    for attempt in range(2):
        result = llm.invoke(scene, messages, prompt_version=prompt_version, schema=schema, **kwargs)
        cost += result.cost
        if result.parsed is not None:
            return result.parsed, cost, None
        if attempt == 0:
            messages = [*messages, ("assistant", result.text[:2000]),
                        ("user", prompts.JSON_RETRY.format(error=result.parse_error))]
    return None, cost, result.parse_error


_default_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
