"""后台任务的进度流（SSE）。

两个信息来源各管一件事：
  · progress 事件  来自 Redis 频道（任务每完成一步发一次），原样转给浏览器
  · done / error    以数据库里的任务状态为准，每一轮顺带查一次
所以浏览器连上来时任务已经跑完、或者中途漏了几条消息，都一定能收到结束事件；不存在"错过 done 就永远等下去"。
"""
from __future__ import annotations

import json
import time
from collections.abc import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.cache.pubsub import Subscribe, get_subscriber
from app.database import get_db, get_session_factory
from app.deps import get_current_user
from app.errors import BAD_REQUEST, NOT_FOUND, ApiError
from app.models import MatchReport, Resume, User
from app.services.parse_service import SessionFactory

router = APIRouter(prefix="/tasks", tags=["tasks"])

POLL_SECONDS = 1.0              # 等频道消息的超时，也就是查库的间隔
HEARTBEAT_SECONDS = 15          # 多久没有事件就发一条注释行，防止代理把空闲连接掐掉
MAX_STREAM_SECONDS = 600

# 后台任务只有两种。kind → (模型, 状态字段)；apply 的 id 就是 match_report 的 id。状态不在"进行中"之列即为结束
_KINDS = {
    "parse": (Resume, "parse_status"),
    "apply": (MatchReport, "status"),
}
_IN_PROGRESS = ("pending", "parsing", "running")


@router.get("/{kind}/{task_ref}/stream")
def stream_task(
    kind: str,
    task_ref: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    session_factory: SessionFactory = Depends(get_session_factory),
    subscribe: Subscribe = Depends(get_subscriber),
):
    if kind not in _KINDS:
        raise ApiError(BAD_REQUEST, f"未知的任务类型：{kind}（可用：{sorted(_KINDS)}）")
    _require_owner(db, user, kind, task_ref)
    return StreamingResponse(
        _events(kind, task_ref, session_factory, subscribe), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})      # 后者让 Nginx 不要缓冲


def _require_owner(db: Session, user: User, kind: str, task_ref: int) -> None:
    """任务归属跟着简历走。别人的、不存在的一律 404。"""
    row = db.get(_KINDS[kind][0], task_ref)
    resume = row if isinstance(row, Resume) else db.get(Resume, row.resume_id) if row else None
    if resume is None or resume.user_id != user.id or resume.is_deleted:
        raise ApiError(NOT_FOUND, "任务不存在")


def _status(session_factory: SessionFactory, kind: str, task_ref: int) -> str | None:
    # 每次用新会话：请求自己的会话在开始流式响应后就不能再用了，而且新事务才能读到任务刚提交的状态
    model, field = _KINDS[kind]
    with session_factory() as db:
        row = db.get(model, task_ref)
        return getattr(row, field) if row else None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _events(kind: str, task_ref: int, session_factory: SessionFactory, subscribe: Subscribe) -> Iterator[str]:
    subscription = subscribe(f"{kind}:{task_ref}")
    started = last_sent = time.monotonic()
    try:
        while time.monotonic() - started < MAX_STREAM_SECONDS:
            status = _status(session_factory, kind, task_ref)
            if status not in _IN_PROGRESS:
                failed = status in ("failed", None)
                yield _sse("error" if failed else "done", {"kind": kind, "id": task_ref, "status": status})
                return
            message = subscription.get(timeout=POLL_SECONDS)
            if message and message.get("event") == "progress":
                yield _sse("progress", message["data"])
                last_sent = time.monotonic()
            elif time.monotonic() - last_sent > HEARTBEAT_SECONDS:
                yield ": keep-alive\n\n"
                last_sent = time.monotonic()
        yield _sse("error", {"kind": kind, "id": task_ref, "status": "timeout"})
    finally:
        subscription.close()
