from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import settings
from app.security import ALGORITHM, hash_password, verify_password

API = "/api/v1/auth"


def test_register_returns_token_and_user(client):
    r = client.post(f"{API}/register", json={"username": "小明_2026", "password": "secret123", "email": "a@b.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0 and body["message"] == "success"
    data = body["data"]
    assert data["token_type"] == "bearer" and data["expires_in"] == settings.JWT_EXPIRE_HOURS * 3600
    assert data["user"]["username"] == "小明_2026" and data["user"]["role"] == "seeker"
    assert "password" not in str(data) and "hash" not in str(data)


def test_duplicate_username_conflicts(client, auth_headers):
    r = client.post(f"{API}/register", json={"username": "tester", "password": "another123"})
    assert r.status_code == 409 and r.json()["code"] == 40901 and r.json()["data"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "ab", "password": "secret123"},                 # 用户名太短
        {"username": "has space", "password": "secret123"},          # 非法字符
        {"username": "tester2", "password": "12345"},                # 密码太短
        {"username": "tester2", "password": "密" * 30},               # 超过 bcrypt 的 72 字节
        {"username": "tester2", "password": "secret123", "email": "not-an-email"},
        {"username": "tester2"},
    ],
)
def test_register_validation(client, payload):
    r = client.post(f"{API}/register", json=payload)
    assert r.status_code == 400
    assert r.json()["code"] == 40001 and r.json()["message"].startswith("参数错误")


def test_login_and_me(client, auth_headers):
    r = client.post(f"{API}/login", json={"username": "tester", "password": "secret123"})
    assert r.status_code == 200
    token = r.json()["data"]["access_token"]

    me = client.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["data"]["username"] == "tester"


def test_wrong_password_and_unknown_user_look_the_same(client, auth_headers):
    wrong = client.post(f"{API}/login", json={"username": "tester", "password": "wrong-password"})
    unknown = client.post(f"{API}/login", json={"username": "nobody", "password": "secret123"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"code": 40101, "message": "用户名或密码错误", "data": None}


def test_me_rejects_missing_bad_and_expired_tokens(client, auth_headers):
    assert client.get(f"{API}/me").status_code == 401
    assert client.get(f"{API}/me", headers={"Authorization": "Bearer not-a-jwt"}).json()["code"] == 40101

    past = datetime.now(timezone.utc) - timedelta(hours=1)
    expired = jwt.encode({"sub": "1", "exp": past}, settings.JWT_SECRET, algorithm=ALGORITHM)
    assert client.get(f"{API}/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401

    forged = jwt.encode({"sub": "1"}, "some-other-secret-key-of-enough-length", algorithm=ALGORITHM)
    assert client.get(f"{API}/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401

    ghost = jwt.encode({"sub": "99999"}, settings.JWT_SECRET, algorithm=ALGORITHM)  # 签名对，但用户不存在
    assert client.get(f"{API}/me", headers={"Authorization": f"Bearer {ghost}"}).status_code == 401


def test_password_hash_is_salted_and_verifiable():
    h1, h2 = hash_password("secret123"), hash_password("secret123")
    assert h1 != h2 and h1.startswith("$2")
    assert verify_password("secret123", h1) and not verify_password("secret124", h1)
    assert not verify_password("secret123", "not-a-bcrypt-hash")


def test_health_is_reachable_without_login(client):
    r = client.get("/api/v1/health")
    assert r.status_code in (200, 503)  # 503 = 本机没开 MySQL / Redis，接口本身仍然可达
    assert {"mysql", "redis", "version"} <= set(r.json()["data"])
