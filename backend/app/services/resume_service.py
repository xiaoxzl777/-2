"""简历上传：校验 → 落盘 → 建记录。解析在 parse_service 里异步完成。

校验清单（FR-B1）按"便宜的先做"的固定顺序执行，任何一步失败即拒收、不落盘不落库：
  ① 扩展名 + 魔数   ② 大小   ③ 能否打开 / 是否加密   ④ 页数上限
DOCX 解析尚未实现，目前只接收 PDF；支持 DOCX 时只需在 _CHECKERS 里加一项。
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import FILE_TOO_LARGE, FILE_TOO_LONG, UNSUPPORTED_FILE, ApiError
from app.models import Resume

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_PDF_MAGIC = b"%PDF-"


@dataclass(slots=True)
class ValidatedUpload:
    file_type: str
    data: bytes
    file_hash: str
    page_count: int | None


def max_upload_bytes() -> int:
    return settings.MAX_UPLOAD_MB * 1024 * 1024


def _check_pdf(data: bytes) -> int:
    """返回页数。打不开、加密、页数超限都在这里拒绝。"""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise ApiError(UNSUPPORTED_FILE, "文件无法打开，可能已损坏") from None
    with doc:
        if doc.needs_pass:
            raise ApiError(UNSUPPORTED_FILE, "文件已加密，请上传未加密的 PDF")
        if doc.page_count > settings.MAX_PDF_PAGES:
            raise ApiError(FILE_TOO_LONG, f"简历不应超过 {settings.MAX_PDF_PAGES} 页（当前 {doc.page_count} 页）")
        return doc.page_count


# 扩展名 → (魔数, 内容检查函数)
_CHECKERS = {"pdf": (_PDF_MAGIC, _check_pdf)}


def validate_upload(filename: str, data: bytes) -> ValidatedUpload:
    """data 由调用方最多读取 max_upload_bytes() + 1 字节，这样超大文件不会被整个读进内存。"""
    ext = Path(filename or "").suffix.lower().lstrip(".")
    if ext not in _CHECKERS:
        raise ApiError(UNSUPPORTED_FILE, "目前只支持 PDF 格式的简历")
    magic, check_content = _CHECKERS[ext]
    if not data.startswith(magic):
        raise ApiError(UNSUPPORTED_FILE, f"文件内容不是有效的 {ext.upper()}")
    if len(data) > max_upload_bytes():
        raise ApiError(FILE_TOO_LARGE, f"文件不能超过 {settings.MAX_UPLOAD_MB}MB")
    page_count = check_content(data)
    return ValidatedUpload(ext, data, hashlib.sha256(data).hexdigest(), page_count)


def display_title(filename: str, title: str | None = None) -> str:
    """只用于展示。落盘文件名一律用 UUID，所以这里不承担防路径穿越的职责。"""
    raw = title or Path((filename or "").replace("\\", "/")).name
    cleaned = _CONTROL_CHARS.sub("", raw).strip()
    return cleaned[:200] or "未命名简历"


def find_duplicate(db: Session, user_id: int, file_hash: str) -> Resume | None:
    """去重范围：本用户、未删除、原始版本。绝不跨用户——否则会把别人的简历 id 泄露出去。"""
    return db.scalar(
        select(Resume).where(
            Resume.user_id == user_id,
            Resume.file_hash == file_hash,
            Resume.is_deleted.is_(False),
            Resume.parent_id.is_(None),
        ).order_by(Resume.id.desc())
    )


def store_file(user_id: int, upload: ValidatedUpload) -> str:
    """以 UUID 命名落盘，返回相对 DATA_DIR 的路径。"""
    relative = Path("uploads") / str(user_id) / f"{uuid.uuid4().hex}.{upload.file_type}"
    target = settings.DATA_DIR / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(upload.data)
    return relative.as_posix()


def create_resume(db: Session, user_id: int, upload: ValidatedUpload, title: str) -> Resume:
    resume = Resume(
        user_id=user_id,
        title=title,
        file_path=store_file(user_id, upload),
        file_type=upload.file_type,
        file_size=len(upload.data),
        file_hash=upload.file_hash,
        page_count=upload.page_count,
    )
    db.add(resume)
    db.commit()
    return resume
