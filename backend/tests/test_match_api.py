"""匹配报告的落库与查询（GET /match/{id}）。匹配由投递触发；这里把诊断设成 rule_only，让它不调模型。"""
from app.config import settings
from app.models import Diagnosis
from tests.conftest import apply, fulltext_reply

API = "/api/v1/match"


def _match(client, headers, rid, jid, **extra) -> int:
    return apply(client, headers, rid, jid, diagnose_mode="rule_only", **extra)["data"]["id"]


def test_hybrid_report(client, auth_headers, resume_and_job, fake_llm):
    rid, jid = resume_and_job
    fake_llm.replies["_FulltextOut"] = [fulltext_reply((3, "hit", "列表查询响应从 820ms 降至 140ms"), (4, "miss", None))]

    report_id = _match(client, auth_headers, rid, jid)
    report = client.get(f"{API}/{report_id}", headers=auth_headers).json()["data"]
    assert (report["status"], report["mode"], report["resume_id"], report["job_id"]) == ("success", "hybrid", rid, jid)
    assert [(i["requirement_id"], i["status"], i["matched_by"]) for i in report["items"]] == [
        (1, "hit", "profile"), (2, "hit", "dict"), (3, "hit", "fulltext"), (4, "miss", "fulltext")]
    assert [i["content"] for i in report["items"]] == ["本科及以上学历", "熟悉 Redis", "有缓存性能优化经验", "熟悉 Kafka"]

    # 每条依据都是简历原文的精确切片
    full_text = client.get(f"/api/v1/resumes/{rid}/blocks", headers=auth_headers).json()["data"]["full_text"]
    located = [i for i in report["items"] if i["char_start"] is not None]
    assert len(located) == 3 and all(full_text[i["char_start"]:i["char_end"]] == i["evidence_quote"] for i in located)

    assert report["overall_match"] == round(100 * 2.5 / 3.5, 1) and report["threshold"] == settings.SCREEN_THRESHOLD
    assert report["passed"] is True and report["dimension_scores"]["skill"] == 50.0
    assert (report["llm_item_count"], report["hallucination_count"]) == (2, 0)
    assert report["cost"] > 0 and report["finished_at"]
    assert len(fake_llm.calls["_FulltextOut"]) == 1                          # 规则判不了的两条要求，一次调用问完


def test_dict_only_never_calls_the_model(client, auth_headers, resume_and_job, fake_llm):
    rid, jid = resume_and_job
    calls_before = dict(fake_llm.calls)
    report_id = _match(client, auth_headers, rid, jid, match_mode="dict_only")
    report = client.get(f"{API}/{report_id}", headers=auth_headers).json()["data"]

    assert [i["status"] for i in report["items"]] == ["hit", "hit", "miss", "miss"]
    assert report["overall_match"] == round(100 * 2 / 3.5, 1) and report["passed"] is False      # 57.1 < 60
    assert fake_llm.calls == calls_before and report["cost"] == 0


def test_report_is_linked_to_the_diagnosis_of_the_same_application(client, auth_headers, resume_and_job, db_session_factory):
    rid, jid = resume_and_job
    started = apply(client, auth_headers, rid, jid, diagnose_mode="rule_only", match_mode="dict_only")["data"]
    report = client.get(f"{API}/{started['id']}", headers=auth_headers).json()["data"]
    assert report["diagnosis_id"] == started["diagnosis_id"]
    with db_session_factory() as db:
        assert db.get(Diagnosis, started["diagnosis_id"]).status == "success"


def test_rejections(client, auth_headers, resume_and_job):
    rid, jid = resume_and_job
    report_id = _match(client, auth_headers, rid, jid, match_mode="dict_only")
    assert client.get(f"{API}/9999", headers=auth_headers).json()["code"] == 40401
    assert client.get(f"{API}/{report_id}").status_code == 401

    other = client.post("/api/v1/auth/register", json={"username": "someone_else", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['data']['access_token']}"}
    assert client.get(f"{API}/{report_id}", headers=other_headers).json()["code"] == 40401      # 别人的报告
