"""岗位：提交 JD、列表、详情、删除。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.llm.client import LLMClient, get_llm_client
from app.models import Job, User
from app.schemas import ApiResponse, JobBrief, JobIn, JobOut, ok
from app.services import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=ApiResponse[JobOut])
def create_job(body: JobIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
               llm: LLMClient = Depends(get_llm_client)):
    """提交目标岗位。同步解析（约 2–4 秒）：返回时要求项已拆好，每条都带 JD 原文的引用区间。"""
    job = job_service.create_job(db, user, body.title, body.company, body.raw_text, llm)
    return ok(_job_out(job))


@router.get("", response_model=ApiResponse[list[JobBrief]])
def list_jobs(include_templates: bool = Query(default=False), user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    return ok([_job_brief(j) for j in job_service.list_jobs(db, user, include_templates)])


@router.get("/{job_id}", response_model=ApiResponse[JobOut])
def get_job(job_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(_job_out(job_service.get_visible_job(db, user, job_id)))


@router.delete("/{job_id}", response_model=ApiResponse[None])
def delete_job(job_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job_service.delete_job(db, user, job_id)
    return ok()


def _job_brief(job: Job) -> JobBrief:
    return JobBrief(id=job.id, title=job.title, company=job.company, is_template=job.is_template,
                    requirement_count=len(job.requirements or []), created_at=job.created_at)


def _job_out(job: Job) -> JobOut:
    return JobOut(**_job_brief(job).model_dump(), raw_text=job.raw_text, requirements=job.requirements or [])
