"""匹配接口测试：假模型 + 内存 Chroma + 假向量，走完 上传 → 提交岗位 → 匹配 → 查看报告。"""
import json
import uuid

import chromadb
import pytest

from app.config import settings
from app.llm.client import LLMError
from app.models import Diagnosis, MatchReport, Resume, Skill
from app.retrieval.unit_store import ResumeUnitStore, get_unit_store
from tests.test_diagnose_api import H_GOOD, _parsed_resume
from tests.test_job import _item, _reply as _jd_reply
from tests.test_retrieval import FakeEmbedder

API = "/api/v1/match"
JD = """任职要求：
1. 本科及以上学历，计算机相关专业；
2. 熟悉 Redis；
3. 有缓存性能优化经验者优先；
4. 熟悉 Kafka 消息队列。"""
JD_REPLY = _jd_reply(
    _item("hard", "education", None, "本科及以上学历，计算机相关专业", "本科及以上学历"),
    _item("hard", "skill", "Redis", "熟悉 Redis", "熟悉 Redis"),
    _item("plus", "experience", None, "有缓存性能优化经验者优先", "有缓存性能优化经验"),
    _item("hard", "skill", "Kafka", "熟悉 Kafka 消息队列", "熟悉 Kafka"),
)


@pytest.fixture
def store(client):
    from app.main import app

    collection = chromadb.EphemeralClient().create_collection(f"t_{uuid.uuid4().hex}", metadata={"hnsw:space": "cosine"},
                                                              embedding_function=None)
    store = ResumeUnitStore(collection, FakeEmbedder())
    app.dependency_overrides[get_unit_store] = lambda: store
    return store


@pytest.fixture
def resume_and_job(client, auth_headers, tmp_path, db_session_factory, fake_llm, store):
    """一份解析好的简历（项目里用了 Redis、学历本科）+ 一个解析好的岗位（4 条要求）。"""
    with db_session_factory() as db:
        db.add(Skill(id=3, canonical_name="Redis", category="middleware", aliases=[]))
        db.commit()
    rid = _parsed_resume(client, auth_headers, tmp_path, db_session_factory)
    with db_session_factory() as db:
        resume = db.get(Resume, rid)
        text = resume.full_text
        edu = "某某大学"
        line_end = text.index("\n", text.index(edu))
        at = text.index("Redis")
        resume.structure = {**resume.structure,
                            "education": [{"degree": "本科", "char_start": text.index(edu), "char_end": line_end}],
                            "skill_mentions": [{"skill_id": 3, "surface": "Redis", "char_start": at, "char_end": at + 5,
                                                "section_type": "projects"}]}
        db.commit()
    fake_llm.replies["_JdOut"] = [JD_REPLY]
    jid = client.post("/api/v1/jobs", headers=auth_headers, json={"title": "后端开发", "raw_text": JD}).json()["data"]["id"]
    return rid, jid


def _judge(status, unit_no=None) -> str:
    return json.dumps({"status": status, "unit_no": unit_no, "reason": "r"}, ensure_ascii=False)


def _full(*results) -> str:
    return json.dumps({"results": [{"id": i, "status": s, "evidence_quote": q, "reason": "r"} for i, s, q in results]},
                      ensure_ascii=False)


def _start(client, headers, rid, jid, **extra):
    return client.post(API, headers=headers, json={"resume_id": rid, "job_id": jid, **extra}).json()


def test_hybrid_match_end_to_end(client, auth_headers, resume_and_job, fake_llm, store, db_session_factory):
    rid, jid = resume_and_job
    with db_session_factory() as db:                                        # 之前做过的诊断会被关联到报告上
        db.add(Diagnosis(resume_id=rid, status="success", mode="hybrid"))
        db.commit()
    fake_llm.replies["_JudgeOut:有缓存性能优化经验"] = [_judge("hit", 1)]
    fake_llm.replies["_JudgeOut:熟悉 Kafka"] = [_judge("miss")]
    fake_llm.replies["_FulltextOut"] = [_full((4, "miss", None))]

    started = _start(client, auth_headers, rid, jid)["data"]
    assert started["task_id"] == f"match:{started['id']}" and started["status"] == "pending"

    report = client.get(f"{API}/{started['id']}", headers=auth_headers).json()["data"]
    assert (report["status"], report["mode"], report["resume_id"], report["job_id"]) == ("success", "hybrid", rid, jid)
    assert [(i["requirement_id"], i["status"], i["matched_by"]) for i in report["items"]] == [
        (1, "hit", "profile"), (2, "hit", "dict"), (3, "hit", "rag"), (4, "miss", "fulltext")]
    assert [i["content"] for i in report["items"]] == ["本科及以上学历", "熟悉 Redis", "有缓存性能优化经验", "熟悉 Kafka"]

    # 每条依据都是简历原文的精确切片
    full_text = client.get(f"/api/v1/resumes/{rid}/blocks", headers=auth_headers).json()["data"]["full_text"]
    located = [i for i in report["items"] if i["char_start"] is not None]
    assert len(located) == 3 and all(full_text[i["char_start"]:i["char_end"]] == i["evidence_quote"] for i in located)

    assert report["overall_match"] == round(100 * 2.5 / 3.5, 1) and report["threshold"] == settings.SCREEN_THRESHOLD
    assert report["passed"] is True and report["dimension_scores"]["skill"] == 50.0
    assert (report["llm_item_count"], report["hallucination_count"]) == (2, 0)
    assert report["diagnosis_id"] is not None and report["cost"] > 0 and report["finished_at"]

    # 简历单元只入库一次：再匹配一遍不会重新向量化整份简历
    embedded = len(store._embedder.embedded)
    _start(client, auth_headers, rid, jid)
    assert len(store._embedder.embedded) - embedded == 2                    # 只有两条要求的查询向量


def test_below_threshold_is_not_passed_and_dict_only_touches_nothing(client, auth_headers, resume_and_job, fake_llm, store):
    rid, jid = resume_and_job
    calls_before = dict(fake_llm.calls)
    report_id = _start(client, auth_headers, rid, jid, mode="dict_only")["data"]["id"]
    report = client.get(f"{API}/{report_id}", headers=auth_headers).json()["data"]

    assert [i["status"] for i in report["items"]] == ["hit", "hit", "miss", "miss"]
    assert report["overall_match"] == round(100 * 2 / 3.5, 1) and report["passed"] is False      # 57.1 < 60
    assert fake_llm.calls == calls_before and store._embedder.embedded == [] and report["cost"] == 0


def test_model_failure_marks_the_report_failed(client, auth_headers, resume_and_job, fake_llm, store):
    rid, jid = resume_and_job
    fake_llm.replies["_JudgeOut:熟悉 Kafka"] = [LLMError("上游超时")]
    report_id = _start(client, auth_headers, rid, jid)["data"]["id"]
    report = client.get(f"{API}/{report_id}", headers=auth_headers).json()["data"]
    assert report["status"] == "failed" and "LLMError" in report["error_msg"] and report["items"] == []
    assert report["passed"] is None


def test_rejections(client, auth_headers, resume_and_job, db_session_factory, store):
    rid, jid = resume_and_job
    assert _start(client, auth_headers, rid, jid, mode="fast")["code"] == 40001
    assert _start(client, auth_headers, rid, jid, model="gpt-99")["code"] == 40001
    assert _start(client, auth_headers, 9999, jid)["code"] == 40401
    assert _start(client, auth_headers, rid, 9999)["code"] == 40401
    assert client.post(API, json={"resume_id": rid, "job_id": jid}).status_code == 401
    assert client.get(f"{API}/9999", headers=auth_headers).json()["code"] == 40401

    report_id = _start(client, auth_headers, rid, jid, mode="dict_only")["data"]["id"]
    other = client.post("/api/v1/auth/register", json={"username": "someone_else", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['data']['access_token']}"}
    assert _start(client, other_headers, rid, jid)["code"] == 40401                       # 别人的简历 / 岗位
    assert client.get(f"{API}/{report_id}", headers=other_headers).json()["code"] == 40401

    with db_session_factory() as db:                                                       # 同一对简历-岗位已有匹配在跑
        db.add(MatchReport(resume_id=rid, job_id=jid, status="running", mode="hybrid"))
        db.commit()
    assert _start(client, auth_headers, rid, jid)["code"] == 40901

    with db_session_factory() as db:                                                       # 简历还在解析
        db.get(Resume, rid).parse_status = "parsing"
        db.commit()
    assert _start(client, auth_headers, rid, jid)["code"] == 40901
