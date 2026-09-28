"""图 B 的检查点：本地 SQLite 文件（DATA_DIR/checkpoints.sqlite），零部署，不需要 Redis Stack。

只负责"让图能从停下的地方接着跑"；面试记录的权威来源是 MySQL（interview_sessions / interview_turns）。
检查点丢了（文件被删、换了机器），interview_service 会用 MySQL 里的记录重建。
整个进程共用一个连接：接口在线程池里执行，所以关掉同线程检查；SqliteSaver 内部自带锁。
"""
from __future__ import annotations

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from app.config import settings

_saver: SqliteSaver | None = None


def get_checkpointer() -> SqliteSaver:
    """FastAPI 依赖，测试时换成内存版。"""
    global _saver
    if _saver is None:
        path = settings.checkpoint_path
        path.parent.mkdir(parents=True, exist_ok=True)
        _saver = SqliteSaver(sqlite3.connect(str(path), check_same_thread=False))
    return _saver


def thread_config(session_id: int) -> dict:
    return {"configurable": {"thread_id": f"interview:{session_id}"}}
