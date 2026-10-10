"""具体建议：结果页上点开一条问题 / 差距时现场生成，流式返回（POST + text/event-stream，docs/03-api 3.3）。

    event: delta  {"text": "…"}                        逐段，前端边收边显示
    event: done   {"text", "violation_count", …}       数字复检之后的全文，以它为准整段替换
    event: error  {"code", "message"}
生成过的直接只回一个 done。
"""
from __future__ import annotations

from collections.abc import Iterable

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.sse import sse_event, sse_response
from app.database import get_db, get_session_factory
from app.deps import get_current_user
from app.llm.client import LLMClient, get_llm_client
from app.models import User
from app.services import advice_service
from app.services.advice_service import AdviceTask
from app.services.parse_service import SessionFactory

router = APIRouter(tags=["advice"])


@router.post("/findings/{finding_id}/advice")
def finding_advice(
    finding_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm: LLMClient = Depends(get_llm_client),
):
    """简历里的一条问题：【问题】【改成】【为什么】。"""
    task = advice_service.finding_task(db, user, finding_id)
    db.close()      # 生成要几秒：先把请求自己的连接还回去，存结果时另开会话
    return _respond(task, llm, session_factory)


@router.post("/match/{report_id}/items/{requirement_id}/advice")
def gap_advice(
    report_id: int,
    requirement_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm: LLMClient = Depends(get_llm_client),
):
    """岗位里没满足 / 部分满足的一条要求：【考察什么】【怎么补】【面试怎么答】。"""
    task = advice_service.gap_task(db, user, report_id, requirement_id)
    db.close()
    return _respond(task, llm, session_factory)


def _respond(task: AdviceTask | dict, llm: LLMClient, session_factory: SessionFactory) -> StreamingResponse:
    events: Iterable[tuple[str, dict]] = (
        [("done", task)] if isinstance(task, dict) else advice_service.run(task, llm, session_factory))
    return sse_response(sse_event(name, data) for name, data in events)
