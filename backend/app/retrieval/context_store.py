"""面试材料的检索：用户贴的面经 / 公司介绍太长（超过 INTERVIEW_CONTEXT_FULL_MAX）时才用。

    创建会话   切段 → 向量化 → 存进 interview_ctx（metadata.session_id 区分会话）
    每个话题   用"话题名 + 考察目标"召回 top-K → reranker 精排 → 取前 N 段给出题的 prompt
    会话结束   删掉这场的切段（隐私：docs/04-design 4.5）

不长的材料整段放进 prompt，不走这里——和"匹配不用 RAG"同一个理由：放得下就不检索（docs/06-workflows 6.5）。
重排失败时退回召回的顺序，功能不中断。
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from app.llm.client import LLMError
from app.llm.embedding import EmbeddingClient, get_embedding_client

if TYPE_CHECKING:                       # 只用来写类型注解；chromadb 导入要 0.7 秒，等真正打开向量库时再加载
    from chromadb.api.models.Collection import Collection

logger = logging.getLogger("app.retrieval")

CHUNK_CHARS = 500           # 每段大约多长
CHUNK_OVERLAP = 80          # 硬切时相邻两段重叠多少字，免得一句话被切在两段里都不完整
_PARAGRAPH = re.compile(r"\n\s*\n|\n(?=\s*(?:\d+[.、)]|[-*•]|【|#))")   # 空行、编号、列表符号处断开


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """按段落切，段落太短就和后面的合并，太长就按 size 硬切（带重叠）。"""
    chunks: list[str] = []
    buf = ""
    for para in (p.strip() for p in _PARAGRAPH.split(text)):
        if not para:
            continue
        if buf and len(buf) + len(para) + 1 > size:
            chunks.append(buf)
            buf = ""
        buf = f"{buf}\n{para}" if buf else para
        while len(buf) > size:
            chunks.append(buf[:size])
            buf = buf[size - overlap:]
    if buf:
        chunks.append(buf)
    return chunks


class ContextStore:
    def __init__(self, collection: Collection, embedder: EmbeddingClient):
        self._collection = collection
        self._embedder = embedder

    def index(self, session_id: int, text: str) -> int:
        """返回切成了几段。向量化失败抛 LLMError，由调用方决定退路。"""
        self.delete(session_id)
        chunks = chunk_text(text)
        if chunks:
            self._collection.add(
                ids=[f"{session_id}:{i}" for i in range(len(chunks))],
                embeddings=self._embedder.embed(chunks, ref=("interview", session_id)),
                documents=chunks, metadatas=[{"session_id": session_id, "idx": i} for i in range(len(chunks))])
        return len(chunks)

    def retrieve(self, session_id: int, query: str, *, recall_k: int, top_k: int) -> list[str]:
        ref = ("interview", session_id)
        found = self._collection.query(query_embeddings=self._embedder.embed([query], ref=ref), n_results=recall_k,
                                       where={"session_id": session_id}, include=["documents"])
        docs = found["documents"][0] if found["documents"] else []
        if len(docs) <= 1:
            return docs[:top_k]
        try:
            return [docs[i] for i, _ in self._embedder.rerank(query, docs, top_k, ref=ref)]
        except LLMError:
            logger.warning("面经重排失败，退回召回顺序 session_id=%s", session_id)
            return docs[:top_k]

    def delete(self, session_id: int) -> None:
        self._collection.delete(where={"session_id": session_id})


_default_store: ContextStore | None = None


def drop_all() -> None:
    """换了向量模型：旧向量和新向量不在一个空间里（维度都可能不一样），所有面试存着的面经切段一起作废。
    正在进行的那几场之后检索不到东西，照样能面，只是不再带面经（图 B 的 retrieve_context 本来就允许查不到）。"""
    global _default_store
    from app.retrieval.chroma_client import INTERVIEW_CTX, drop_collection

    drop_collection(INTERVIEW_CTX)
    _default_store = None               # 手里那个集合对象已经失效，下次重新打开


def get_context_store() -> ContextStore | None:
    """FastAPI 依赖。第一次用到时才打开 Chroma。打不开（数据目录坏了、升级后格式不兼容）时返回 None、下次再试：
    只有贴了长面经的面试才用得上向量库，不能因为它让所有面试接口都 500。调用方按 None 处理：长面经退回整段截取、不检索。"""
    global _default_store
    if _default_store is None:
        try:
            from app.retrieval.chroma_client import INTERVIEW_CTX, get_collection

            _default_store = ContextStore(get_collection(INTERVIEW_CTX), get_embedding_client())
        except Exception:                               # noqa: BLE001
            logger.exception("向量库打不开，面试先不用检索")
            return None
    return _default_store
