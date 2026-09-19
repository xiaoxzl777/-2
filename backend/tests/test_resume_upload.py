from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models import ParsedBlock, Resume

API = "/api/v1/resumes"


def _upload(client, headers, path: Path, filename: str | None = None, **form):
    with path.open("rb") as f:
        return client.post(API, headers=headers, files={"file": (filename or path.name, f, "application/pdf")}, data=form)


def test_upload_parses_in_background_and_persists(client, auth_headers, single_column_pdf, db_session_factory):
    r = _upload(client, auth_headers, single_column_pdf, filename="张三的简历.pdf")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["task_id"] == f"parse:{data['id']}" and data["deduplicated"] is False

    # TestClient 会在响应返回后同步跑完后台任务，所以这里已经解析完成
    detail = client.get(f"{API}/{data['id']}", headers=auth_headers).json()["data"]
    assert detail["title"] == "张三的简历.pdf" and detail["file_type"] == "pdf" and detail["page_count"] == 1
    assert detail["parse_status"] == "success" and detail["parse_error"] is None
    assert detail["layout_type"] == "single" and detail["layout_confidence"] == 1.0

    with db_session_factory() as db:
        resume = db.get(Resume, data["id"])
        blocks = db.scalars(select(ParsedBlock).where(ParsedBlock.resume_id == resume.id)
                            .order_by(ParsedBlock.block_index)).all()
        # 系统不变量②在落库之后依然成立
        assert blocks and all(resume.full_text[b.char_start:b.char_end] == b.text for b in blocks)
        assert [s["type"] for s in resume.sections] == ["basics", "education", "projects"]
        assert resume.layout_detail == [{"page_no": 1, "layout_type": "single", "confidence": 1.0, "gap": None}]
        assert resume.ats_signals["images"] == 0

        stored = settings.DATA_DIR / resume.file_path
        assert stored.exists() and stored.read_bytes() == single_column_pdf.read_bytes()
        # 落盘文件名是 UUID，与用户给的文件名无关
        assert resume.file_path.startswith(f"uploads/{resume.user_id}/") and "张三" not in resume.file_path


def test_same_file_twice_is_deduplicated(client, auth_headers, single_column_pdf, db_session_factory):
    first = _upload(client, auth_headers, single_column_pdf).json()["data"]
    second = _upload(client, auth_headers, single_column_pdf, filename="renamed.pdf").json()["data"]
    assert second["id"] == first["id"] and second["deduplicated"] is True and second["parse_status"] == "success"
    with db_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Resume)) == 1


def test_dedup_never_crosses_users(client, auth_headers, single_column_pdf):
    mine = _upload(client, auth_headers, single_column_pdf).json()["data"]
    token = client.post("/api/v1/auth/register", json={"username": "someone_else", "password": "secret123"})
    other = {"Authorization": f"Bearer {token.json()['data']['access_token']}"}

    theirs = _upload(client, other, single_column_pdf).json()["data"]
    assert theirs["id"] != mine["id"] and theirs["deduplicated"] is False
    # 别人的简历对我来说不存在
    assert client.get(f"{API}/{mine['id']}", headers=other).status_code == 404
    assert client.get(f"{API}/{mine['id']}", headers=other).json()["code"] == 40401


def test_scanned_pdf_is_accepted_but_parse_fails_with_reason(client, auth_headers, image_only_pdf):
    rid = _upload(client, auth_headers, image_only_pdf).json()["data"]["id"]
    detail = client.get(f"{API}/{rid}", headers=auth_headers).json()["data"]
    assert detail["parse_status"] == "failed" and detail["parse_error"] == "scanned_pdf"


def test_failed_parse_is_retried_on_reupload(client, auth_headers, image_only_pdf, db_session_factory):
    rid = _upload(client, auth_headers, image_only_pdf).json()["data"]["id"]
    with db_session_factory() as db:
        db.get(Resume, rid).parse_error = "interrupted"
        db.commit()
    again = _upload(client, auth_headers, image_only_pdf).json()["data"]
    assert again["id"] == rid and again["deduplicated"] is True
    detail = client.get(f"{API}/{rid}", headers=auth_headers).json()["data"]
    assert detail["parse_error"] == "scanned_pdf"  # 重新解析过了，原因被刷新


def test_display_title_strips_path_and_control_chars():
    from app.services.resume_service import display_title

    assert display_title("..\\..\\evil\x00na\x1fme.pdf") == "evilname.pdf"
    assert display_title("/etc/passwd/../我的简历.pdf") == "我的简历.pdf"
    assert display_title("a.pdf", title="  投字节的版本  ") == "投字节的版本"
    assert display_title("") == "未命名简历" and len(display_title("x" * 500)) == 200


def test_path_in_filename_never_reaches_the_disk(client, auth_headers, single_column_pdf, db_session_factory):
    rid = _upload(client, auth_headers, single_column_pdf, filename="..\\..\\evil.pdf").json()["data"]["id"]
    assert client.get(f"{API}/{rid}", headers=auth_headers).json()["data"]["title"] == "evil.pdf"
    with db_session_factory() as db:
        assert ".." not in db.get(Resume, rid).file_path


def test_title_form_field_overrides_filename(client, auth_headers, tmp_path):
    from tests.conftest import make_pdf
    pdf = make_pdf(tmp_path / "x.pdf", [(40, 100 + i * 20, f"line {i} " + "word " * 12, 10, "helv") for i in range(8)])
    rid = _upload(client, auth_headers, pdf, title="投字节的版本").json()["data"]["id"]
    assert client.get(f"{API}/{rid}", headers=auth_headers).json()["data"]["title"] == "投字节的版本"


@pytest.mark.parametrize(
    ("filename", "content", "status", "code"),
    [
        ("resume.docx", b"PK\x03\x04 whatever", 415, 41501),          # 暂不支持 DOCX
        ("resume.exe", b"MZ\x90\x00", 415, 41501),
        ("fake.pdf", b"MZ\x90\x00 this is not a pdf", 415, 41501),    # 扩展名对、魔数不对
        ("broken.pdf", b"%PDF-1.7 truncated garbage", 415, 41501),    # 魔数对、但打不开
        ("noext", b"%PDF-1.7", 415, 41501),
    ],
)
def test_rejects_unsupported_files(client, auth_headers, filename, content, status, code):
    r = client.post(API, headers=auth_headers, files={"file": (filename, content, "application/octet-stream")})
    assert r.status_code == status and r.json()["code"] == code and r.json()["data"] is None


def test_rejects_encrypted_too_long_and_too_large(client, auth_headers, encrypted_pdf, tmp_path, monkeypatch):
    assert _upload(client, auth_headers, encrypted_pdf).json()["code"] == 41501

    doc = pymupdf.open()
    for _ in range(settings.MAX_PDF_PAGES + 1):
        doc.new_page().insert_text((40, 100), "page of text " * 10, fontsize=10)
    long_pdf = tmp_path / "long.pdf"
    doc.save(long_pdf)
    r = _upload(client, auth_headers, long_pdf)
    assert r.status_code == 422 and r.json()["code"] == 42201

    from app.services import resume_service
    monkeypatch.setattr(resume_service, "max_upload_bytes", lambda: 100)
    r = _upload(client, auth_headers, long_pdf)
    assert r.status_code == 413 and r.json()["code"] == 41301


def test_nothing_is_stored_when_validation_fails(client, auth_headers, db_session_factory):
    client.post(API, headers=auth_headers, files={"file": ("fake.pdf", b"not a pdf", "application/pdf")})
    with db_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Resume)) == 0
    assert not (settings.DATA_DIR / "uploads").exists()


def test_upload_requires_login(client, single_column_pdf):
    assert _upload(client, {}, single_column_pdf).status_code == 401
