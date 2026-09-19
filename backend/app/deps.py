"""FastAPI 依赖：当前登录用户、当前用户名下的简历。"""
from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import NOT_FOUND, UNAUTHORIZED, ApiError
from app.models import Resume, User
from app.security import decode_access_token

# auto_error=False：缺少令牌时由我们抛统一格式的 40101，而不是 FastAPI 默认的 403
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    user_id = decode_access_token(credentials.credentials) if credentials else None
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise ApiError(UNAUTHORIZED, "未登录或登录已过期")
    return user


def get_owned_resume(
    resume_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Resume:
    """所有 /resumes/{resume_id}/... 接口共用。别人的、已删除的简历一律视同不存在（404），不暴露其存在。"""
    resume = db.get(Resume, resume_id)
    if resume is None or resume.user_id != user.id or resume.is_deleted:
        raise ApiError(NOT_FOUND, "简历不存在")
    return resume
