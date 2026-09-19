"""简历：上传、查询、删除。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db, get_session_factory
from app.deps import get_current_user, get_owned_resume, get_parsed_resume
from app.llm.client import LLMClient, get_llm_client
from app.models import ParsedBlock, Resume, User
from app.schemas import ApiResponse, BlockOut, BlocksOut, Page, ResumeOut, UploadOut, ok
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
    llm: LLMClient = Depends(get_llm_client),
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
        background.add_task(parse_resume, resume.id, session_factory, llm)

    return ok(UploadOut(id=resume.id, task_id=f"parse:{resume.id}",
                        parse_status=resume.parse_status, deduplicated=deduplicated))


@router.get("", response_model=ApiResponse[Page[ResumeOut]])
def list_resumes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """当前用户的简历，最近更新的在前。"""
    mine = (Resume.user_id == user.id) & Resume.is_deleted.is_(False)
    total = db.scalar(select(func.count()).select_from(Resume).where(mine))
    rows = db.scalars(
        select(Resume).where(mine)
        .order_by(Resume.updated_at.desc(), Resume.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ok(Page[ResumeOut](items=[ResumeOut.model_validate(r) for r in rows],
                              total=total, page=page, page_size=page_size))


@router.get("/{resume_id}", response_model=ApiResponse[ResumeOut])
def get_resume(resume: Resume = Depends(get_owned_resume)):
    return ok(ResumeOut.model_validate(resume))


@router.delete("/{resume_id}", response_model=ApiResponse[None])
def delete_resume(resume: Resume = Depends(get_owned_resume), db: Session = Depends(get_db)):
    """软删除：之后对用户不可见；文件与数据保留 30 天后由清理任务物理删除。"""
    resume.is_deleted, resume.deleted_at = True, datetime.now()
    db.commit()
    return ok()


@router.get("/{resume_id}/blocks", response_model=ApiResponse[BlocksOut])
def get_blocks(resume: Resume = Depends(get_parsed_resume), db: Session = Depends(get_db)):
    """解析结果：按阅读顺序排好的块、章节划分、版面判定。前端据此渲染原文并按 char 区间高亮。"""
    blocks = db.scalars(
        select(ParsedBlock).where(ParsedBlock.resume_id == resume.id).order_by(ParsedBlock.block_index)
    ).all()
    return ok(BlocksOut(
        layout_type=resume.layout_type,
        layout_confidence=resume.layout_confidence,
        layout_detail=resume.layout_detail,
        used_llm_fallback=resume.used_llm_fallback,
        full_text=resume.full_text or "",
        blocks=[_block_out(b) for b in blocks],
        sections=resume.sections or [],
    ))


@router.get("/{resume_id}/structure", response_model=ApiResponse[dict])
def get_structure(resume: Resume = Depends(get_parsed_resume)):
    """结构化结果：基本信息、教育、经历、项目、技能、奖项。每个条目都带 block_ids 与 char 区间。"""
    return ok(resume.structure or {})


def _block_out(b: ParsedBlock) -> BlockOut:
    has_bbox = None not in (b.x0, b.y0, b.x1, b.y1)
    return BlockOut(
        block_index=b.block_index, page_no=b.page_no, column_index=b.column_index,
        bbox=[b.x0, b.y0, b.x1, b.y1] if has_bbox else None,
        text=b.text, font_size=b.font_size, is_bold=b.is_bold,
        char_start=b.char_start, char_end=b.char_end,
    )
