"""压测前后的准备和收尾：python scripts/loadtest/prepare.py <命令>

    seed [--users 200]   建临时账号（lt_000 …），每人克隆几份已经解析好的简历，签好令牌，写进状态文件
    use-fake             在管理端把对话模型换成假模型（后端和 fake_llm.py 都要开着）
    flush                两轮之间：清掉假模型的结果缓存，下一轮每次调用仍然真的发出去
    use-env              换回 .env 里的配置，删掉假模型那一条
    clean                删掉临时账号和它们的全部数据、假模型的调用记录和缓存

为什么克隆简历而不是上传：上传要调模型做结构化抽取，假模型给不出像样的结果；克隆的是 --source 账号（默认 user）
名下已经解析好的简历，那些都是虚构内容。换模型走管理端的接口而不是直接改库：「现在用哪家」是后端进程里的一份状态。
状态文件在 data/eval_runs/ 下（不进仓库），里面有临时账号的令牌，locustfile.py 读它。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from app.cache.redis_client import redis_client  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Job, LlmCall, LlmProvider, ParsedBlock, Resume, User  # noqa: E402
from app.security import create_access_token, hash_password  # noqa: E402

PREFIX = "lt_"                                  # 临时账号的用户名前缀；clean 只认这个前缀
FAKE_MODEL = "loadtest-fake"                    # 同 fake_llm.py 的 MODEL
STATE = BACKEND.parent / "data" / "eval_runs" / "loadtest-state.json"


def _temp_users(db):
    return db.query(User).filter(User.username.like("lt\\_%", escape="\\"))


def _copy(row, skip: tuple[str, ...]) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in skip}


def seed(users: int, source: str) -> None:
    with SessionLocal() as db:
        if _temp_users(db).count():
            sys.exit("已经有 lt_ 开头的临时账号了，先跑 clean")
        owner = db.query(User).filter(User.username == source).one()
        sources = (db.query(Resume).filter(Resume.user_id == owner.id, Resume.is_deleted.is_(False),
                                           Resume.parse_status == "success").order_by(Resume.id).all())
        if not sources:
            sys.exit(f"{source} 名下没有解析好的简历")
        blocks = {r.id: db.query(ParsedBlock).filter(ParsedBlock.resume_id == r.id).order_by(ParsedBlock.id).all()
                  for r in sources}
        jobs = [j.id for j in db.query(Job).filter(Job.is_template.is_(True), Job.is_deleted.is_(False)).order_by(Job.id)]
        password = hash_password("loadtest-only")       # 只算一次：bcrypt 故意慢，这些账号也不走登录，直接用签好的令牌

        accounts = []
        for i in range(users):
            user = User(username=f"{PREFIX}{i:03d}", email=f"{PREFIX}{i:03d}@loadtest.local", password_hash=password)
            db.add(user)
            db.flush()
            clones = []
            for src in sources:
                clone = Resume(**_copy(src, ("id", "user_id", "created_at")), user_id=user.id)
                db.add(clone)
                db.flush()
                db.bulk_insert_mappings(ParsedBlock, [{**_copy(b, ("id", "resume_id")), "resume_id": clone.id}
                                                      for b in blocks[src.id]])
                clones.append(clone.id)
            accounts.append({"id": user.id, "username": user.username, "token": create_access_token(user.id),
                             "resumes": clones})
        db.commit()
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"users": accounts, "jobs": jobs}, ensure_ascii=False), encoding="utf-8")
    print(f"建了 {users} 个临时账号，每人 {len(sources)} 份简历；岗位模板 {len(jobs)} 个；状态文件 {STATE}")


@contextmanager
def _admin(base: str) -> Iterator[httpx.Client]:
    """登录管理员，给出带令牌的客户端。trust_env=False：本机有系统代理，走代理访问 localhost 会被拒。"""
    with httpx.Client(base_url=f"{base}/api/v1", trust_env=False, timeout=60) as client:
        reply = client.post("/auth/login", json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD})
        reply.raise_for_status()
        client.headers["Authorization"] = f"Bearer {reply.json()['data']['access_token']}"
        yield client


def _check(reply: httpx.Response) -> dict:
    body = reply.json()
    if body.get("code") != 0:
        sys.exit(f"接口返回 {body.get('code')}：{body.get('message')}")
    return body


def use_fake(base: str, fake_url: str) -> None:
    with _admin(base) as client:
        draft = {"kind": "custom", "name": "压测假模型", "base_url": fake_url, "model": FAKE_MODEL,
                 "api_key": "loadtest-key-not-real", "price_in": 0, "price_out": 0}
        created = _check(client.post("/admin/providers", json=draft))["data"]     # 保存前后端会真调一次，假模型没开就存不上
        _check(client.post(f"/admin/providers/{created['id']}/activate"))
    print(f"对话模型换成了假模型（{fake_url}，id = {created['id']}）")


def use_env(base: str) -> None:
    with _admin(base) as client, SessionLocal() as db:
        _check(client.post("/admin/providers/0/activate"))                       # 0 = .env 里的那一家；切换前会真调一次
        for row in db.query(LlmProvider).filter(LlmProvider.model == FAKE_MODEL):
            _check(client.delete(f"/admin/providers/{row.id}"))
    print("换回了 .env 里的配置，假模型那一条删掉了")


def flush() -> int:
    keys = list(redis_client.scan_iter(match=f"llm:*:{FAKE_MODEL}:*", count=1000))   # 只碰假模型的结果缓存
    for start in range(0, len(keys), 500):
        redis_client.delete(*keys[start:start + 500])
    print(f"清掉 {len(keys)} 条假模型的结果缓存")
    return len(keys)


def clean() -> None:
    with SessionLocal() as db:
        if db.query(LlmProvider).filter(LlmProvider.model == FAKE_MODEL, LlmProvider.is_active.is_(True)).count():
            sys.exit("假模型还在用着，先跑 use-env")
        ids = [u.id for u in _temp_users(db)]
        resumes = db.query(Resume).filter(Resume.user_id.in_(ids)).delete(synchronize_session=False) if ids else 0
        users = _temp_users(db).delete(synchronize_session=False)       # 简历先删：块、诊断、问题、投递由外键级联带走
        calls = db.query(LlmCall).filter(LlmCall.model_name == FAKE_MODEL).delete(synchronize_session=False)
        db.commit()
    flush()
    STATE.unlink(missing_ok=True)
    print(f"删了 {users} 个临时账号、{resumes} 份简历（连同投递和诊断）、{calls} 条假模型的调用记录")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="压测前后的准备和收尾")
    parser.add_argument("command", choices=["seed", "use-fake", "flush", "use-env", "clean"])
    parser.add_argument("--users", type=int, default=200)
    parser.add_argument("--source", default="user", help="克隆谁名下的简历")
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="后端地址")
    parser.add_argument("--fake", default="http://127.0.0.1:9100/v1", help="假模型的地址")
    args = parser.parse_args()
    if args.command == "seed":
        seed(args.users, args.source)
    elif args.command == "use-fake":
        use_fake(args.base, args.fake)
    elif args.command == "use-env":
        use_env(args.base)
    elif args.command == "flush":
        flush()
    else:
        clean()
