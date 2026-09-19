from pathlib import Path

from app.models import Resume
from tests.conftest import make_pdf, upload_pdf
from tests.test_layout import _two_column_items

API = "/api/v1/resumes"


def _upload(client, headers, path: Path) -> int:
    return upload_pdf(client, headers, path).json()["data"]["id"]


def _other_user(client) -> dict:
    r = client.post("/api/v1/auth/register", json={"username": "someone_else", "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def _distinct_pdf(tmp_path, n: int) -> Path:
    items = [(40, 100 + i * 20, f"resume {n} line {i} " + "word " * 10, 10, "helv") for i in range(8)]
    return make_pdf(tmp_path / f"r{n}.pdf", items)


def test_list_is_paginated_newest_first_and_scoped_to_me(client, auth_headers, tmp_path):
    ids = [_upload(client, auth_headers, _distinct_pdf(tmp_path, n)) for n in range(3)]
    _upload(client, _other_user(client), _distinct_pdf(tmp_path, 99))

    page1 = client.get(API, headers=auth_headers, params={"page": 1, "page_size": 2}).json()["data"]
    assert page1["total"] == 3 and page1["page"] == 1 and page1["page_size"] == 2
    assert [r["id"] for r in page1["items"]] == ids[::-1][:2]

    page2 = client.get(API, headers=auth_headers, params={"page": 2, "page_size": 2}).json()["data"]
    assert [r["id"] for r in page2["items"]] == ids[:1]
    # 列表里不带 full_text 这类大字段
    assert "full_text" not in page1["items"][0] and "structure" not in page1["items"][0]


def test_list_rejects_bad_paging(client, auth_headers):
    assert client.get(API, headers=auth_headers, params={"page": 0}).json()["code"] == 40001
    assert client.get(API, headers=auth_headers, params={"page_size": 1000}).json()["code"] == 40001
    assert client.get(API).status_code == 401


def test_blocks_returns_reading_order_sections_and_consistent_offsets(client, auth_headers, tmp_path):
    rid = _upload(client, auth_headers, make_pdf(tmp_path / "two.pdf", _two_column_items()))
    data = client.get(f"{API}/{rid}/blocks", headers=auth_headers).json()["data"]

    assert data["layout_type"] == "double" and data["used_llm_fallback"] is False
    assert data["layout_detail"][0]["gap"] is not None
    blocks = data["blocks"]
    assert [b["block_index"] for b in blocks] == list(range(len(blocks)))
    assert all(data["full_text"][b["char_start"]:b["char_end"]] == b["text"] for b in blocks)
    assert all(len(b["bbox"]) == 4 for b in blocks)
    assert {b["column_index"] for b in blocks} == {-1, 0, 1}
    # 先读完左栏再读右栏
    columns = [b["column_index"] for b in blocks if b["column_index"] >= 0]
    assert columns == sorted(columns)
    assert data["sections"] and data["sections"][0]["block_start"] == 0


def test_blocks_of_failed_or_foreign_resume(client, auth_headers, image_only_pdf, single_column_pdf):
    failed = _upload(client, auth_headers, image_only_pdf)
    r = client.get(f"{API}/{failed}/blocks", headers=auth_headers)
    assert r.status_code == 500 and r.json()["code"] == 50003 and "扫描件" in r.json()["message"]

    mine = _upload(client, auth_headers, single_column_pdf)
    assert client.get(f"{API}/{mine}/blocks", headers=_other_user(client)).status_code == 404
    assert client.get(f"{API}/999999/blocks", headers=auth_headers).json()["code"] == 40401


def test_blocks_while_still_parsing_is_a_conflict(client, auth_headers, single_column_pdf, db_session_factory):
    rid = _upload(client, auth_headers, single_column_pdf)
    with db_session_factory() as db:
        db.get(Resume, rid).parse_status = "parsing"
        db.commit()
    r = client.get(f"{API}/{rid}/blocks", headers=auth_headers)
    assert r.status_code == 409 and r.json()["code"] == 40901


def test_delete_is_soft_and_hides_the_resume(client, auth_headers, single_column_pdf, db_session_factory):
    rid = _upload(client, auth_headers, single_column_pdf)
    assert client.delete(f"{API}/{rid}", headers=auth_headers).json() == {"code": 0, "message": "success", "data": None}

    assert client.get(f"{API}/{rid}", headers=auth_headers).status_code == 404
    assert client.get(f"{API}/{rid}/blocks", headers=auth_headers).status_code == 404
    assert client.delete(f"{API}/{rid}", headers=auth_headers).status_code == 404
    assert client.get(API, headers=auth_headers).json()["data"]["total"] == 0
    with db_session_factory() as db:  # 行还在，只是打了标记
        row = db.get(Resume, rid)
        assert row.is_deleted and row.deleted_at is not None

    # 删除后重新上传同一文件：不复用已删除的那条，而是新建
    again = _upload(client, auth_headers, single_column_pdf)
    assert again != rid


def test_cannot_delete_someone_elses_resume(client, auth_headers, single_column_pdf):
    rid = _upload(client, auth_headers, single_column_pdf)
    assert client.delete(f"{API}/{rid}", headers=_other_user(client)).status_code == 404
    assert client.get(f"{API}/{rid}", headers=auth_headers).status_code == 200
