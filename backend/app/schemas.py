"""接口的请求 / 响应模型（Pydantic）。所有响应统一包在 ApiResponse 里。"""
from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")

BCRYPT_MAX_BYTES = 72  # bcrypt 只处理前 72 字节，超出直接拒绝，避免"两个不同密码都能登录"


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: T | None = None


def ok(data=None) -> dict:
    return {"code": 0, "message": "success", "data": data}


# ───────────── 认证 ─────────────


class _Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_一-鿿]+$")
    password: str = Field(min_length=6, max_length=64)

    @field_validator("password")
    @classmethod
    def _fits_bcrypt(cls, v: str) -> str:
        if len(v.encode("utf-8")) > BCRYPT_MAX_BYTES:
            raise ValueError("密码过长")
        return v


class RegisterIn(_Credentials):
    email: str | None = Field(default=None, max_length=100, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginIn(_Credentials):
    pass


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    role: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒
    user: UserOut
