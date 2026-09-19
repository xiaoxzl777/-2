"""测试用 PDF 由代码现场生成，不依赖任何真实简历文件。"""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

A4 = (595, 842)


def make_pdf(path: Path, items: list[tuple], *, encrypt: bool = False) -> Path:
    """items: [(x, y, text, fontsize, fontname)]；fontname: 'china-s' 中文, 'helv' 常规, 'hebo' 加粗。"""
    doc = pymupdf.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    for x, y, text, size, font in items:
        page.insert_text((x, y), text, fontsize=size, fontname=font)
    if encrypt:
        doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    else:
        doc.save(path)
    doc.close()
    return path


@pytest.fixture
def single_column_pdf(tmp_path) -> Path:
    body = "负责订单服务的开发与性能优化，使用 Spring Boot 与 Redis 完成缓存改造并上线，"
    items = [
        (250, 60, "Zhang San", 24, "hebo"),
        (40, 120, "Education", 12, "hebo"),
        (40, 140, "某某大学 计算机科学与技术 本科 2023.09-2027.06", 10.5, "china-s"),
        (40, 180, "Projects", 12, "hebo"),
    ]
    items += [(40, 200 + i * 16, f"{i + 1}. {body}", 10.5, "china-s") for i in range(6)]
    return make_pdf(tmp_path / "single.pdf", items)


@pytest.fixture
def image_only_pdf(tmp_path) -> Path:
    """模拟扫描件：页面上只有一张图，没有文本层。"""
    doc = pymupdf.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), False)
    pix.clear_with(200)
    page.insert_image(pymupdf.Rect(50, 50, 545, 792), pixmap=pix)
    path = tmp_path / "scanned.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def encrypted_pdf(tmp_path) -> Path:
    return make_pdf(tmp_path / "enc.pdf", [(40, 100, "secret resume " * 20, 10.5, "helv")], encrypt=True)


# ───────────── 接口测试：SQLite 内存库替换 MySQL，不跑 lifespan（因此也不需要 Redis）─────────────


@pytest.fixture
def db_session_factory():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models import Base

    # StaticPool：所有连接共用同一个内存库；接口在线程池里执行，所以关掉同线程检查
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


class FakeLLM:
    """脚本化的假模型。replies 的键可以是 schema 类名，或 "类名:某段文字"——后者只在 prompt 里出现这段文字时命中，
    用来区分同一 schema 的多次调用（不同章节、不同经历）。并行调用下结果依然确定。

    找不到预设回复时返回一个对所有 schema 都合法的空结果，所以接口测试不必关心结构化抽取。
    """

    EMPTY = '{"entries": [], "items": []}'

    def __init__(self, replies: dict[str, list] | None = None):
        self.replies = {k: list(v) for k, v in (replies or {}).items()}
        self.calls: dict[str, list] = {}

    def invoke(self, scene, messages, *, prompt_version, schema=None, ref=None, **_):
        from app.llm.client import LLMResult, parse_json

        name = schema.__name__ if schema else scene
        haystack = "\n".join(content for _, content in messages)
        key = next((k for k in self.replies if k.startswith(f"{name}:") and k.split(":", 1)[1] in haystack), name)
        self.calls.setdefault(key, []).append(list(messages))
        queue = self.replies.get(key)
        reply = queue.pop(0) if queue else self.EMPTY
        if isinstance(reply, Exception):
            raise reply
        parsed, error = parse_json(reply, schema) if schema else (None, None)
        return LLMResult(reply, parsed, error, 100, 50, 0.001, False, "fake", "fp", 1)

    @property
    def sent_text(self) -> str:
        return "\n".join(content for calls in self.calls.values() for msgs in calls for _, content in msgs)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def client(db_session_factory, fake_llm, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.database import get_db, get_session_factory
    from app.llm.client import get_llm_client
    from app.main import app

    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")  # 上传文件落到临时目录，不碰真实 data/
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_factory] = lambda: db_session_factory  # 后台任务也用测试库
    app.dependency_overrides[get_llm_client] = lambda: fake_llm                 # 不发真实的模型请求
    yield TestClient(app)  # 不用 with：不触发 lifespan 里的 MySQL / Redis 检查
    app.dependency_overrides.clear()


def upload_pdf(client, headers: dict, path: Path, filename: str | None = None, **form):
    """POST /resumes。TestClient 会在响应返回后同步跑完后台解析，所以返回时解析已结束。"""
    with path.open("rb") as f:
        files = {"file": (filename or path.name, f, "application/pdf")}
        return client.post("/api/v1/resumes", headers=headers, files=files, data=form)


@pytest.fixture
def auth_headers(client) -> dict:
    r = client.post("/api/v1/auth/register", json={"username": "tester", "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
