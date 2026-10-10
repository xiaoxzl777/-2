"""Chroma 嵌入式向量库：数据落在 DATA_DIR/chroma，随进程启动，不需要单独的服务。"""
from __future__ import annotations

from functools import lru_cache

import chromadb
from chromadb.api.models.Collection import Collection

from app.config import settings

INTERVIEW_CTX = "interview_ctx"      # 模拟面试：用户贴的长面经切段，会话结束即删


@lru_cache(maxsize=1)
def _client() -> chromadb.ClientAPI:
    path = settings.DATA_DIR / "chroma"
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path), settings=chromadb.Settings(anonymized_telemetry=False))


def drop_collection(name: str) -> None:
    """整个集合删掉（下次用到时重新建）。换了向量模型时用：集合的维度在第一次写入时就定死了，只删记录不够。"""
    try:
        _client().delete_collection(name)
    except Exception:  # noqa: BLE001 —— 本来就不存在（Chroma 各版本抛的异常类型不一样）
        pass


def get_collection(name: str) -> Collection:
    """向量由我们自己算好传入（经 llm/embedding.py 审计与限流），所以不给 Chroma 配 embedding_function。"""
    return _client().get_or_create_collection(name, metadata={"hnsw:space": "cosine"}, embedding_function=None)
