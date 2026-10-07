"""投递：把简历投给一个岗位，后台一次跑完 诊断 + 匹配 + 初筛（图 A）。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.cache.pubsub import Publish, get_publisher
from app.config import settings
from app.database import get_db, get_session_factory
from app.deps import get_current_user, load_owned_report, load_owned_resume, require_parsed
from app.domains import get_domain
from app.errors import BAD_REQUEST, ApiError
from app.llm.client import LLMClient, get_llm_client
from app.llm.registry import MODEL_REGISTRY
from app.models import Diagnosis, User
from app.schemas import ApiResponse, ApplyBrief, ApplyIn, ApplyOut, ApplyStartOut, FindingOut, GateOut, Page, ok
from app.services import apply_service, interview_service, job_service
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
    background.add_task(apply_service.run_apply, report.id, session_factory, llm, publish)
    return ok(ApplyStartOut(id=report.id, diagnosis_id=report.diagnosis_id, task_id=f"apply:{report.id}",
                            status=report.status))


@router.get("", response_model=ApiResponse[Page[ApplyBrief]])
def list_applies(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """我的投递：新的在前，每条带上结论和这次投递下面的面试。"""
    total, rows = apply_service.list_applies(db, user, page, page_size)
    items = [ApplyBrief(
        id=report.id, status=report.status,
        overall_match=float(report.overall_match) if report.overall_match is not None else None,
        passed=report.passed if report.status == "success" else None,
        failure=apply_service.failure_of(report, resume),
        job_id=job.id, job_title=job.title, company=job.company, domain=get_domain(job.domain).key,
        resume_id=resume.id, resume_title=resume.title, created_at=report.created_at,
        interviews=[interview_service.brief(s) for s in sessions],
    ) for report, job, resume, sessions in rows]
    return ok(Page[ApplyBrief](items=items, total=total, page=page, page_size=page_size))


@router.get("/{apply_id}", response_model=ApiResponse[ApplyOut])
def get_apply(apply_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """初筛结果。未通过时 gaps + resume_issues 就是"哪里不符合"；完整明细见 GET /match/{id} 与诊断接口。"""
    report, resume = load_owned_report(db, user, apply_id)

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
        resume_issues=[FindingOut.model_validate(f) for f in apply_service.resume_issues(db, report)] if done else [],
        interviews=[interview_service.brief(s) for s in apply_service.interviews_of(db, [report.id])[report.id]]))
