"""密码哈希（bcrypt）、登录令牌（JWT，HS256）、存库的 API Key 加解密（Fernet）。"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from functools import cache

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

ALGORITHM = "HS256"
BCRYPT_ROUNDS = 12          # bcrypt 默认强度，一次约 0.37 秒；测试里改成 4


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:  # 哈希格式损坏
        return False


@cache
def dummy_hash() -> str:
    """用户名不存在时也验一次这个假哈希，让"用户不存在"和"密码错误"耗时相同，无法靠响应时间探测用户名。
    第一次登录时才算（启动时就算要多等约 0.4 秒）。"""
    return hash_password("dummy-password-for-timing")


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


# ───────────── 管理端填的 API Key：加密后才存库 ─────────────


@cache
def _fernet() -> Fernet:
    """加密用的钥匙从 JWT_SECRET 派生，不另外多一个要保管的配置项。
    代价：JWT_SECRET 换了，库里存的 Key 就解不开了，要在管理端重新填一遍。"""
    digest = hashlib.sha256(f"llm-provider-key:{settings.JWT_SECRET}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(text: str) -> str:
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str | None:
    """解不开（JWT_SECRET 换过、数据被改过）返回 None，由调用方决定怎么提示。"""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
