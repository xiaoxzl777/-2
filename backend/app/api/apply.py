"""投递：把简历投给一个岗位，后台一次跑完 诊断 + 匹配 + 初筛（图 A）。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.cache.pubsub import Publish, get_publisher
from app.config import settings
from app.database import get_db, get_session_factory
from app.deps import get_current_user, load_owned_resume, require_parsed
from app.errors import BAD_REQUEST, NOT_FOUND, ApiError
from app.llm.client import LLMClient, get_llm_client
from app.llm.registry import MODEL_REGISTRY
from app.models import Diagnosis, MatchReport, Resume, User
from app.retrieval.unit_store import ResumeUnitStore, get_unit_store
from app.schemas import ApiResponse, ApplyIn, ApplyOut, ApplyStartOut, FindingOut, GateOut, ok
from app.services import apply_service, job_service
from app.services.parse_service import SessionFactory

router = APIRouter(prefix="/apply", tags=["apply"])


@router.post("", response_model=ApiResponse[ApplyStartOut])
def start_apply(
    body: ApplyIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm: LLMClient = Depends(get_llm_client),
    store: ResumeUnitStore = Depends(get_unit_store),
    publish: Publish = Depends(get_publisher),
):
    """刚上传、还在解析的简历也可以投：后台任务会先等解析完成。解析已经失败的直接报错。"""
    resume = load_owned_resume(db, user, body.resume_id)
    if resume.parse_status == "failed":
        require_parsed(resume)
    job = job_service.get_visible_job(db, user, body.job_id)
    if body.model is not None and body.model not in MODEL_REGISTRY:
        raise ApiError(BAD_REQUEST, f"未知的模型：{body.model}（可用：{sorted(MODEL_REGISTRY)}）")

    report = apply_service.create_apply(db, resume, job, body.diagnose_mode, body.match_mode, body.model)
    background.add_task(apply_service.run_apply, report.id, session_factory, llm, store, publish)
    return ok(ApplyStartOut(id=report.id, diagnosis_id=report.diagnosis_id, task_id=f"apply:{report.id}",
                            status=report.status))


@router.get("/{apply_id}", response_model=ApiResponse[ApplyOut])
def get_apply(apply_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """初筛结果。未通过时 gaps + resume_issues 就是"哪里不符合"；完整明细见 GET /match/{id} 与诊断接口。"""
    report = db.get(MatchReport, apply_id)
    resume = db.get(Resume, report.resume_id) if report else None
    if resume is None or resume.user_id != user.id or resume.is_deleted:
        raise ApiError(NOT_FOUND, "投递记录不存在")

    done = report.status == "success"
    diagnosis = db.get(Diagnosis, report.diagnosis_id) if report.diagnosis_id else None
    overall = float(report.overall_match) if report.overall_match is not None else None
    return ok(ApplyOut(
        id=report.id, resume_id=report.resume_id, job_id=report.job_id, diagnosis_id=report.diagnosis_id,
        status=report.status, stage=apply_service.stage_of(report, resume), error_msg=report.error_msg,
        gate=GateOut(passed=bool(report.passed), overall_match=overall, threshold=settings.SCREEN_THRESHOLD) if done else None,
        dimension_scores=report.dimension_scores,
        resume_score=float(diagnosis.overall_score) if diagnosis and diagnosis.overall_score is not None else None,
        gaps=apply_service.gap_items(report) if done else [],
        resume_issues=[FindingOut.model_validate(f) for f in apply_service.resume_issues(db, report)] if done else []))
