"""Chroma 嵌入式向量库：数据落在 DATA_DIR/chroma，随进程启动，不需要单独的服务。"""
from __future__ import annotations

from functools import lru_cache

import chromadb
from chromadb.api.models.Collection import Collection

from app.config import settings

RESUME_UNITS = "resume_units"


@lru_cache(maxsize=1)
def _client() -> chromadb.ClientAPI:
    path = settings.DATA_DIR / "chroma"
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path), settings=chromadb.Settings(anonymized_telemetry=False))


def get_collection(name: str) -> Collection:
    """向量由我们自己算好传入（经 llm/embedding.py 审计与限流），所以不给 Chroma 配 embedding_function。"""
    return _client().get_or_create_collection(name, metadata={"hnsw:space": "cosine"}, embedding_function=None)
