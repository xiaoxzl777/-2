"""认证：注册、登录、当前用户。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.errors import CONFLICT, UNAUTHORIZED, ApiError
from app.models import User
from app.schemas import ApiResponse, LoginIn, RegisterIn, TokenOut, UserOut, ok
from app.security import (
    DUMMY_HASH,
    create_access_token,
    hash_password,
    token_lifetime_seconds,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: User) -> dict:
    return ok(TokenOut(
        access_token=create_access_token(user.id),
        expires_in=token_lifetime_seconds(),
        user=UserOut.model_validate(user),
    ))


@router.post("/register", response_model=ApiResponse[TokenOut])
def register(body: RegisterIn, db: Session = Depends(get_db)):
    """注册成功直接返回令牌，前端无需再调一次登录。角色固定为 seeker。"""
    user = User(username=body.username, email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # 依赖唯一索引判重，避免"先查后插"的并发竞争
        db.rollback()
        raise ApiError(CONFLICT, "用户名或邮箱已被注册") from None
    return _token_response(user)


@router.post("/login", response_model=ApiResponse[TokenOut])
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    password_ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not password_ok:
        raise ApiError(UNAUTHORIZED, "用户名或密码错误")  # 不区分是哪一个错，防止探测用户名
    return _token_response(user)


@router.get("/me", response_model=ApiResponse[UserOut])
def me(user: User = Depends(get_current_user)):
    return ok(UserOut.model_validate(user))
