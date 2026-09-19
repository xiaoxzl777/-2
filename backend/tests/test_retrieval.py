"""检索层：embedding / rerank 客户端（httpx MockTransport，不联网）、匹配单元、Chroma 两阶段检索（内存库 + 假向量）。"""
import hashlib
import json
import uuid

import chromadb
import httpx
import pytest

from app.diagnose.types import ReviewUnit
from app.llm import embedding
from app.llm.client import LLMError
from app.llm.embedding import EmbeddingClient
from app.matching.units import build_match_units
from app.retrieval.unit_store import ResumeUnitStore

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


# ───────────── 匹配单元 ─────────────


def test_match_units_cover_experience_skill_lines_and_awards():
    lines = ["专业技能", "1.Java生态：", "熟悉 Java 并发编程与 JVM 内存模型", "缓存：熟悉 Redis", "项目经历",
             "订单系统", "热点数据预热至 Redis，响应降至 140ms", "荣誉", "英语 CET-6"]
    text = "\n".join(lines)
    at = lambda s: {"char_start": text.index(s), "char_end": text.index(s) + len(s)}  # noqa: E731
    structure = {"projects": [{"name": "订单系统", **at("订单系统\n热点数据预热至 Redis，响应降至 140ms"), "highlights": [at(lines[6])]}],
                 "awards": [at("英语 CET-6")]}
    sections = [{"type": "skills", "title": "专业技能", "char_start": 0, "char_end": text.index("项目经历") - 1},
                {"type": "projects", "title": "项目经历", "char_start": text.index("项目经历"), "char_end": text.index("荣誉") - 1}]

    units = build_match_units(structure, sections, text)
    assert [(u.unit_id, u.entry_name, u.text) for u in units] == [
        ("projects[0].highlights[0]", "订单系统", lines[6]),
        ("skills.line[2]", "Java生态", lines[2]), ("skills.line[3]", "Java生态", lines[3]),   # 小标题不是单元，而是分组名
        ("awards[0]", None, "英语 CET-6")]
    assert all(text[u.char_start:u.char_end] == u.text for u in units)


# ───────────── 两阶段检索 ─────────────


class FakeEmbedder:
    """字符二元组哈希成 64 维词袋：共用的字越多越相似。重排按与 query 的共有字符数打分。"""

    def __init__(self):
        self.embedded: list[str] = []
        self.reranked: list[list[str]] = []

    def embed(self, texts, *, ref=None):
        self.embedded += list(texts)
        return [self._vector(t) for t in texts]

    def rerank(self, query, documents, top_n, *, ref=None):
        self.reranked.append(list(documents))
        scores = [(i, len(set(query) & set(d)) / len(set(query))) for i, d in enumerate(documents)]
        return sorted(scores, key=lambda pair: -pair[1])[:top_n]

    @staticmethod
    def _vector(text: str) -> list[float]:
        v = [0.0] * 64
        for a, b in zip(text, text[1:]):
            v[int(hashlib.md5((a + b).encode()).hexdigest(), 16) % 64] += 1.0
        return v


UNITS_TEXT = "\n".join(["热点商品数据预热至 Redis 缓存，查询响应降至 140ms", "基于 Vue3 开发后台管理页面",
                        "使用 RabbitMQ 做订单异步削峰", "张三 13800138000 负责部署"])


def _units() -> list[ReviewUnit]:
    out, pos = [], 0
    for i, line in enumerate(UNITS_TEXT.split("\n")):
        out.append(ReviewUnit(f"projects[0].highlights[{i}]", "projects", "电商平台", pos, pos + len(line), line))
        pos += len(line) + 1
    return out


@pytest.fixture
def store():
    collection = chromadb.EphemeralClient().create_collection(f"t_{uuid.uuid4().hex}", metadata={"hnsw:space": "cosine"},
                                                              embedding_function=None)
    return ResumeUnitStore(collection, FakeEmbedder())


def test_recall_then_rerank(store):
    store.index(7, _units(), UNITS_TEXT)
    store.index(8, _units()[1:2], UNITS_TEXT)                                   # 另一份简历，不应被检索到

    got = store.retrieve(7, "熟悉 Redis 缓存", recall_k=3, top_k=2)
    assert [c.unit_id for c in got][0] == "projects[0].highlights[0]" and len(got) == 2
    assert got[0].score >= got[1].score and got[0].entry_name == "电商平台"
    assert UNITS_TEXT[got[0].char_start:got[0].char_end] == got[0].text
    assert len(store._embedder.reranked[-1]) == 3                               # 精排的输入是召回的 3 条
    assert all(d.startswith("电商平台：") for d in store._embedder.reranked[-1])  # 带着所属经历的名字

    plain = store.retrieve(7, "熟悉 Redis 缓存", recall_k=3, top_k=2, use_rerank=False)
    assert len(plain) == 2 and len(store._embedder.reranked) == 1               # 关掉精排：直接取召回的前 2 条


def test_index_is_idempotent_and_rebuilt_when_units_change(store):
    units = _units()
    assert store.ensure_indexed(7, units, UNITS_TEXT) is True
    embedded = len(store._embedder.embedded)
    assert store.ensure_indexed(7, units, UNITS_TEXT) is False and len(store._embedder.embedded) == embedded

    assert store.ensure_indexed(7, units[:2], UNITS_TEXT) is True               # 结构被纠正过 → 整份重建
    assert len(store.retrieve(7, "Redis", recall_k=10, top_k=10, use_rerank=False)) == 2
    store.delete(7)
    assert store.retrieve(7, "Redis", recall_k=10, top_k=10) == []


def test_only_masked_text_is_stored_and_sent(store):
    from app.parser.pii import mask_pii

    masked = mask_pii(UNITS_TEXT, name="张三")
    store.index(7, _units(), masked)
    sent = "".join(store._embedder.embedded)
    assert "13800138000" not in sent and "张三" not in sent
    got = store.retrieve(7, "负责部署", recall_k=4, top_k=4, use_rerank=False)
    assert all("13800138000" not in c.text for c in got)
