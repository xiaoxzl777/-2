"""简历检索单元的向量索引与两阶段检索：embedding 召回 top-K → reranker 精排 top-N。

一份简历的全部单元共用一个 collection，靠 metadata.resume_id 过滤。索引是幂等的：
ensure_indexed 发现库里的单元与当前结构不一致（首次匹配、或结构被人工纠正过）就整份重建。
存进去、发出去的都是 PII 掩码后的文本；展示给用户时按 char 区间回到 full_text 取原文。
"""
from __future__ import annotations

from chromadb.api.models.Collection import Collection

from app.diagnose.types import ReviewUnit
from app.llm.embedding import EmbeddingClient, get_embedding_client
from app.matching.units import Candidate


class ResumeUnitStore:
    def __init__(self, collection: Collection, embedder: EmbeddingClient):
        self._collection = collection
        self._embedder = embedder

    def ensure_indexed(self, resume_id: int, units: list[ReviewUnit], masked_text: str) -> bool:
        """返回 True 表示这次（重新）建了索引。"""
        existing = self._collection.get(where={"resume_id": resume_id}, include=[])["ids"]
        if set(existing) == {_doc_id(resume_id, u) for u in units}:
            return False
        self.index(resume_id, units, masked_text)
        return True

    def index(self, resume_id: int, units: list[ReviewUnit], masked_text: str) -> None:
        self.delete(resume_id)
        if not units:
            return
        texts = [_embed_text(u, masked_text) for u in units]
        self._collection.add(
            ids=[_doc_id(resume_id, u) for u in units],
            embeddings=self._embedder.embed(texts, ref=("resume", resume_id)),
            documents=[masked_text[u.char_start:u.char_end] for u in units],
            metadatas=[{"resume_id": resume_id, "unit_id": u.unit_id, "unit_type": u.unit_type,
                        "entry_name": u.entry_name or "", "char_start": u.char_start, "char_end": u.char_end}
                       for u in units])

    def delete(self, resume_id: int) -> None:
        self._collection.delete(where={"resume_id": resume_id})

    def retrieve(self, resume_id: int, query: str, *, recall_k: int, top_k: int, use_rerank: bool = True,
                 ref: tuple[str, int] | None = None) -> list[Candidate]:
        found = self._collection.query(
            query_embeddings=self._embedder.embed([query], ref=ref), n_results=recall_k,
            where={"resume_id": resume_id}, include=["documents", "metadatas", "distances"])
        recalled = [
            Candidate(meta["unit_id"], meta["unit_type"], meta["entry_name"] or None, meta["char_start"],
                      meta["char_end"], doc, round(1 - distance, 4))
            for doc, meta, distance in zip(found["documents"][0], found["metadatas"][0], found["distances"][0])]
        if not use_rerank or len(recalled) <= 1:
            return recalled[:top_k]
        ranked = self._embedder.rerank(query, [_with_entry(c.entry_name, c.text) for c in recalled], top_k, ref=ref)
        return [_rescored(recalled[i], score) for i, score in ranked]


def _doc_id(resume_id: int, unit: ReviewUnit) -> str:
    # 区间也进 id：结构被纠正后同名单元的范围变了，要能触发重建
    return f"{resume_id}:{unit.unit_id}:{unit.char_start}-{unit.char_end}"


def _with_entry(entry_name: str | None, text: str) -> str:
    """带上所属经历的名字再向量化 / 重排："优化了查询性能"单看不知道是哪个项目里的事。"""
    return f"{entry_name}：{text}" if entry_name else text


def _embed_text(unit: ReviewUnit, masked_text: str) -> str:
    return _with_entry(unit.entry_name, masked_text[unit.char_start:unit.char_end])


def _rescored(c: Candidate, score: float) -> Candidate:
    return Candidate(c.unit_id, c.unit_type, c.entry_name, c.char_start, c.char_end, c.text, round(score, 4))


_default_store: ResumeUnitStore | None = None


def get_unit_store() -> ResumeUnitStore:
    """FastAPI 依赖。第一次用到时才打开 Chroma：不做匹配的请求不必为它付出启动开销。"""
    global _default_store
    if _default_store is None:
        from app.retrieval.chroma_client import RESUME_UNITS, get_collection

        _default_store = ResumeUnitStore(get_collection(RESUME_UNITS), get_embedding_client())
    return _default_store
