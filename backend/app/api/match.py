"""匹配报告查询。匹配本身由投递（POST /apply）触发，不单独提供触发接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.errors import NOT_FOUND, ApiError
from app.models import MatchReport, Resume, User
from app.schemas import ApiResponse, MatchReportOut, ok

router = APIRouter(prefix="/match", tags=["match"])


@router.get("/{report_id}", response_model=ApiResponse[MatchReportOut])
def get_match(report_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """逐条要求的完整明细。报告 id 就是投递 id。"""
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
