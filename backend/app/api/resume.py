"""简历：上传与查询。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db, get_session_factory
from app.deps import get_current_user, get_owned_resume
from app.models import Resume, User
from app.schemas import ApiResponse, ResumeOut, UploadOut, ok
from app.services import resume_service
from app.services.parse_service import SessionFactory, parse_resume

router = APIRouter(prefix="/resumes", tags=["resumes"])



@router.post("", response_model=ApiResponse[UploadOut])
def upload_resume(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    session_factory: SessionFactory = Depends(get_session_factory),
):
    """上传简历（PDF）。立即返回，解析在后台进行：轮询 GET /resumes/{id} 查看 parse_status。"""
    data = file.file.read(resume_service.max_upload_bytes() + 1)  # 多读 1 字节即可判断超限，不必读完整个大文件
    upload = resume_service.validate_upload(file.filename or "", data)

    resume = resume_service.find_duplicate(db, user.id, upload.file_hash)
    deduplicated = resume is not None
    if resume is None:
        resume = resume_service.create_resume(
            db, user.id, upload, resume_service.display_title(file.filename or "", title))

    # 复用旧记录时只有 failed 才重新解析：pending / parsing 说明已有任务在路上，再排一个会并发写出重复的块
    if not deduplicated or resume.parse_status == "failed":
        background.add_task(parse_resume, resume.id, session_factory)

    return ok(UploadOut(id=resume.id, task_id=f"parse:{resume.id}",
                        parse_status=resume.parse_status, deduplicated=deduplicated))


@router.get("/{resume_id}", response_model=ApiResponse[ResumeOut])
def get_resume(resume: Resume = Depends(get_owned_resume)):
    return ok(ResumeOut.model_validate(resume))
