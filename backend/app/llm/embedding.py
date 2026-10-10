"""向量化与重排的唯一出口。用哪家、哪两个模型看 llm/provider.retrieval()：管理端改过就用改的，否则是 .env 里的硅基流动（bge-m3 / bge-reranker-v2-m3）。

与 llm/client.py 同样的纪律：限流占位 → 调接口 → 记审计；默认直连、不走系统代理。
不做结果缓存：面经切段的向量本身就存在 Chroma 里，查询向量很短、接口又免费，缓存收益抵不上复杂度。

没有用 LangChain 的 OpenAIEmbeddings：它拿不到 token 用量（审计要记），而重排接口 LangChain 没有现成集成，
两个接口放在同一个薄客户端里更简单。送进来的文本由调用方负责先做 PII 掩码（系统不变量⑤）。
"""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence

import httpx

from app.cache import ratelimit
from app.config import settings
from app.llm import audit, provider, registry
from app.llm.client import LLMError

EMBED_BATCH = 32            # 接口单次最多接收的条数
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


class EmbeddingClient:
    def __init__(
        self,
        http: httpx.Client | None = None,
        acquire: Callable[[str, int], None] = ratelimit.acquire,
        write_audit: Callable[[dict], None] = audit.write_llm_call,
    ):
        self._http = http
        self._acquire = acquire
        self._write_audit = write_audit

    def embed(self, texts: Sequence[str], *, ref: tuple[str, int] | None = None) -> list[list[float]]:
        """返回与 texts 等长、顺序一致的向量。"""
        vectors: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH):
            batch = list(texts[i:i + EMBED_BATCH])
            model = provider.retrieval().embed_model
            data = self._post("embed", "/embeddings", {"model": model, "input": batch}, model, ref)
            vectors += [row["embedding"] for row in sorted(data["data"], key=lambda row: row["index"])]
        return vectors

    def rerank(self, query: str, documents: Sequence[str], top_n: int, *,
               ref: tuple[str, int] | None = None) -> list[tuple[int, float]]:
        """返回 [(documents 的下标, 相关度)]，相关度从高到低，最多 top_n 个。"""
        if not documents:
            return []
        model = provider.retrieval().rerank_model
        payload = {"model": model, "query": query, "documents": list(documents),
                   "top_n": min(top_n, len(documents)), "return_documents": False}
        data = self._post("rerank", "/rerank", payload, model, ref)
        return [(r["index"], float(r["relevance_score"])) for r in data["results"]]

    # ───────────── 内部 ─────────────

    def _client(self) -> httpx.Client:
        """和对话模型共用一个 httpx 客户端（默认直连）。地址和 Key 每次请求现取：管理端改了马上生效。"""
        return self._http or registry.http_client()

    def _post(self, scene: str, path: str, payload: dict, model: str, ref: tuple[str, int] | None) -> dict:
        kind = provider.retrieval().kind
        record = {"scene": scene, "ref_type": ref[0] if ref else None, "ref_id": ref[1] if ref else None,
                  "provider": kind, "model_name": model}
        started = time.perf_counter()
        try:
            self._acquire(kind, settings.SILICONFLOW_RPM)     # Redis 不通、排队超时也按调用失败处理
            data = self._post_with_retry(path, payload)
        except Exception as e:
            self._write_audit({**record, "success": False, "latency_ms": _elapsed_ms(started),
                               "error_msg": f"{type(e).__name__}: {e}"[:500]})
            raise LLMError(f"{scene} 调用 {model} 失败：{type(e).__name__}") from e
        tokens = (data.get("usage") or {}).get("total_tokens") or \
                 ((data.get("meta") or {}).get("tokens") or {}).get("input_tokens", 0)
        self._write_audit({**record, "token_input": tokens, "latency_ms": _elapsed_ms(started)})
        return data

    def _post_with_retry(self, path: str, payload: dict) -> dict:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                r = provider.retrieval()
                response = self._client().post(f"{r.base_url.rstrip('/')}{path}", json=payload,
                                               headers={"Authorization": f"Bearer {r.api_key}"})
                if response.status_code not in _RETRY_STATUS or attempt == _MAX_ATTEMPTS:
                    response.raise_for_status()
                    return response.json()
            except httpx.TransportError:
                if attempt == _MAX_ATTEMPTS:
                    raise
            time.sleep(0.5 * 2 ** (attempt - 1))       # 指数退避：0.5s、1s
        raise AssertionError("unreachable")


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


_default_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    global _default_client
    if _default_client is None:
        _default_client = EmbeddingClient()
    return _default_client
