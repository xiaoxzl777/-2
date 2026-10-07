"""检索层的 embedding / rerank 客户端（httpx MockTransport，不联网）。面经检索（context_store）的测试在 test_interview.py。"""
import json

import httpx
import pytest

from app.llm import embedding
from app.llm.client import LLMError
from app.llm.embedding import EmbeddingClient

# ───────────── EmbeddingClient ─────────────


def _client(handler, audits: list) -> EmbeddingClient:
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test/v1")
    return EmbeddingClient(http=http, acquire=lambda *_: None, write_audit=audits.append)


def test_embed_batches_and_keeps_input_order(monkeypatch):
    monkeypatch.setattr(embedding, "EMBED_BATCH", 2)
    audits, batches = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        batches.append(texts)
        rows = [{"index": i, "embedding": [float(len(t))]} for i, t in enumerate(texts)]
        return httpx.Response(200, json={"data": rows[::-1], "usage": {"total_tokens": 7}})    # 故意乱序返回

    vectors = _client(handler, audits).embed(["a", "bb", "ccc"], ref=("resume", 5))
    assert vectors == [[1.0], [2.0], [3.0]] and batches == [["a", "bb"], ["ccc"]]
    assert [(a["scene"], a["ref_type"], a["ref_id"], a["provider"], a["token_input"]) for a in audits] == [
        ("embed", "resume", 5, "siliconflow", 7)] * 2


def test_rerank_returns_index_score_pairs():
    audits = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path.endswith("/rerank") and body["top_n"] == 2 and body["return_documents"] is False
        return httpx.Response(200, json={"results": [{"index": 2, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}],
                                         "meta": {"tokens": {"input_tokens": 30}}})

    client = _client(handler, audits)
    assert client.rerank("q", ["x", "y", "z"], top_n=2) == [(2, 0.9), (0, 0.1)]
    assert audits[0]["scene"] == "rerank" and audits[0]["token_input"] == 30
    assert client.rerank("q", [], top_n=3) == [] and len(audits) == 1                          # 没有文档就不发请求


def test_transient_errors_are_retried_and_hard_failures_are_audited(monkeypatch):
    monkeypatch.setattr(embedding.time, "sleep", lambda _: None)
    audits, statuses = [], [503, 429, 200]

    def flaky(_: httpx.Request) -> httpx.Response:
        status = statuses.pop(0)
        return httpx.Response(status, json={"data": [{"index": 0, "embedding": [1.0]}]} if status == 200 else {})

    assert _client(flaky, audits).embed(["a"]) == [[1.0]] and statuses == []

    with pytest.raises(LLMError):
        _client(lambda _: httpx.Response(401, json={"message": "bad key"}), audits).embed(["a"])
    assert audits[-1]["success"] is False and "HTTPStatusError" in audits[-1]["error_msg"]
