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


@pytest.fixture
def client(db_session_factory):
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app

    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)  # 不用 with：不触发 lifespan 里的 MySQL / Redis 检查
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client) -> dict:
    r = client.post("/api/v1/auth/register", json={"username": "tester", "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
