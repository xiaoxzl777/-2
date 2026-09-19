"""FastAPI 依赖：当前登录用户。"""
from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import UNAUTHORIZED, ApiError
from app.models import User
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
