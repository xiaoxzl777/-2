"""模拟面试（图 B）。创建时同步定下话题；之后每一步都是 POST + text/event-stream 的同步流式响应（docs/03-api 3.3）。

    POST /interviews                    {apply_id, company_name?, extra_context?, practice?} → 会话
    POST /interviews/{id}/start         开始 / 继续：出下一题（中途失败了也用它从原处继续）
    POST /interviews/{id}/answer        {text, skip?} → 练习模式先给上一题的点评，然后出下一题或结束
    POST /interviews/{id}/finish        提前结束：按已答的题出报告
    GET  /interviews/{id}               会话 + 已问到的话题 + 问答（页面刷新后恢复用）
    GET  /interviews/{id}/report        报告 + 逐题回顾
"""
from __future__ import annotations

from collections.abc import Iterable

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.task import sse_event
from app.config import settings
from app.database import get_db, get_session_factory
from app.deps import get_current_user
from app.graphs.checkpoint import get_checkpointer
from app.llm.client import LLMClient, get_llm_client
from app.models import MatchReport, User
from app.retrieval.context_store import ContextStore, get_context_store
from app.schemas import (AnswerIn, ApiResponse, GateOut, InterviewCreated, InterviewIn, InterviewOut,
                         InterviewReportOut, ok)
from app.services import interview_service
from app.services.parse_service import SessionFactory

router = APIRouter(prefix="/interviews", tags=["interview"])


@router.post("", response_model=ApiResponse[InterviewCreated])
def create_interview(
    body: InterviewIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm_client),
    store: ContextStore = Depends(get_context_store),
    checkpointer=Depends(get_checkpointer),
):
    """要几秒：面经太长时先切段向量化，然后一次模型调用定下话题。"""
    session = interview_service.create_interview(
        db, user, apply_id=body.apply_id, company_name=body.company_name, extra_context=body.extra_context,
        practice=body.practice, llm=llm, store=store, checkpointer=checkpointer)
    report = db.get(MatchReport, session.match_report_id)
    return ok(InterviewCreated(
        id=session.id, mode=session.mode, topic_count=len(session.plan["topics"]),
        context_mode=session.plan["materials"]["context_mode"],
        gate=GateOut(passed=bool(report.passed), overall_match=float(report.overall_match or 0),
                     threshold=settings.SCREEN_THRESHOLD)))


@router.post("/{session_id}/start")
def start_interview(
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm: LLMClient = Depends(get_llm_client),
    store: ContextStore = Depends(get_context_store),
    checkpointer=Depends(get_checkpointer),
):
    session = interview_service.load_owned(db, user, session_id)
    interview_service.begin(db, session)
    return _stream(interview_service.advance(session_id, None, llm=llm, store=store, checkpointer=checkpointer,
                                             session_factory=session_factory))


@router.post("/{session_id}/answer")
def answer_question(
    session_id: int,
    body: AnswerIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm: LLMClient = Depends(get_llm_client),
    store: ContextStore = Depends(get_context_store),
    checkpointer=Depends(get_checkpointer),
):
    session = interview_service.load_owned(db, user, session_id)
    answer = interview_service.submit_answer(db, session, body.text, body.skip)
    return _stream(interview_service.advance(session_id, answer, llm=llm, store=store, checkpointer=checkpointer,
                                             session_factory=session_factory))


@router.post("/{session_id}/finish", response_model=ApiResponse[InterviewReportOut])
def finish_interview(
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm_client),
    store: ContextStore = Depends(get_context_store),
    checkpointer=Depends(get_checkpointer),
):
    session = interview_service.load_owned(db, user, session_id)
    interview_service.finish_early(db, session, llm=llm, store=store, checkpointer=checkpointer)
    return ok(interview_service.report_view(db, session))


@router.get("/{session_id}", response_model=ApiResponse[InterviewOut])
def get_interview(session_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(interview_service.view(db, interview_service.load_owned(db, user, session_id)))


@router.get("/{session_id}/report", response_model=ApiResponse[InterviewReportOut])
def get_report(session_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(interview_service.report_view(db, interview_service.load_owned(db, user, session_id)))


def _stream(events: Iterable[tuple[str, dict]]) -> StreamingResponse:
    return StreamingResponse(
        (sse_event(name, data) for name, data in events), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})      # 后者让 Nginx 不要缓冲
