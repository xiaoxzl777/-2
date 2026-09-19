"""密码哈希（bcrypt）与登录令牌（JWT，HS256）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:  # 哈希格式损坏
        return False


# 用户名不存在时也验一次这个假哈希，让"用户不存在"和"密码错误"耗时相同，无法靠响应时间探测用户名
DUMMY_HASH = hash_password("dummy-password-for-timing")


def token_lifetime_seconds() -> int:
    return settings.JWT_EXPIRE_HOURS * 3600


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(seconds=token_lifetime_seconds())}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """返回 user_id；令牌无效或过期返回 None。"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
