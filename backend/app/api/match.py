"""匹配：触发与查询。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, get_session_factory
from app.deps import get_current_user, load_owned_resume, require_parsed
from app.errors import BAD_REQUEST, NOT_FOUND, ApiError
from app.llm.client import LLMClient, get_llm_client
from app.llm.registry import MODEL_REGISTRY
from app.models import MatchReport, Resume, User
from app.retrieval.unit_store import ResumeUnitStore, get_unit_store
from app.schemas import ApiResponse, MatchIn, MatchReportOut, TaskOut, ok
from app.services import job_service, match_service
from app.services.parse_service import SessionFactory

router = APIRouter(prefix="/match", tags=["match"])


@router.post("", response_model=ApiResponse[TaskOut])
def start_match(
    body: MatchIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm: LLMClient = Depends(get_llm_client),
    store: ResumeUnitStore = Depends(get_unit_store),
):
    """拿一份简历去匹配一个岗位（后台执行）。轮询 GET /match/{id} 查看结果。"""
    resume = require_parsed(load_owned_resume(db, user, body.resume_id))
    job = job_service.get_visible_job(db, user, body.job_id)
    if body.model is not None and body.model not in MODEL_REGISTRY:
        raise ApiError(BAD_REQUEST, f"未知的模型：{body.model}（可用：{sorted(MODEL_REGISTRY)}）")

    report = match_service.create_match(db, resume, job, body.mode, body.model)
    background.add_task(match_service.run_match, report.id, session_factory, llm, store)
    return ok(TaskOut(id=report.id, task_id=f"match:{report.id}", status=report.status))


@router.get("/{report_id}", response_model=ApiResponse[MatchReportOut])
def get_match(report_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report = db.get(MatchReport, report_id)
    resume = db.get(Resume, report.resume_id) if report else None
    if resume is None or resume.user_id != user.id or resume.is_deleted:
        raise ApiError(NOT_FOUND, "匹配报告不存在")
    return ok(MatchReportOut(
        id=report.id, resume_id=report.resume_id, job_id=report.job_id, status=report.status,
        error_msg=report.error_msg, mode=report.mode, model_name=report.model_name,
        prompt_version=report.prompt_version,
        overall_match=float(report.overall_match) if report.overall_match is not None else None,
        passed=report.passed, threshold=settings.SCREEN_THRESHOLD, dimension_scores=report.dimension_scores,
        items=report.items or [], llm_item_count=report.llm_item_count,
        hallucination_count=report.hallucination_count, diagnosis_id=report.diagnosis_id, cost=float(report.cost),
        started_at=report.started_at, finished_at=report.finished_at))
