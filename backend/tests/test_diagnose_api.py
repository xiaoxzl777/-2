"""诊断结果的落库与查询（GET /resumes/{id}/diagnosis）。诊断由投递触发；这里把匹配设成 dict_only，让它不干扰。"""
from app.config import settings
from app.llm.client import LLMError
from app.models import Finding
from tests.conftest import H_GOOD, H_VAGUE, apply, parsed_resume, review_reply

API = "/api/v1/resumes"


def _diagnose(client, headers, rid, jid, **extra) -> int:
    return apply(client, headers, rid, jid, match_mode="dict_only", **extra)["data"]["diagnosis_id"]


def test_findings_are_persisted_located_and_counted(client, auth_headers, resume_and_job, db_session_factory, fake_llm):
    rid, jid = resume_and_job
    fake_llm.replies[f"_ReviewOut:{H_VAGUE}"] = [
        review_reply(("vague", "medium", "持续改进各项功能"), ("exaggeration", "high", "主导了整个公司的架构升级")),  # 第二条是编的
        review_reply(),                                                                                              # 重试：放弃
    ]
    did = _diagnose(client, auth_headers, rid, jid)

    data = client.get(f"{API}/{rid}/diagnosis", headers=auth_headers).json()["data"]
    assert (data["id"], data["status"], data["mode"], data["job_title"]) == (did, "success", "hybrid", "后端开发")
    assert data["prompt_version"] and data["started_at"] and data["finished_at"]

    stats = data["stats"]
    assert (stats["units_total"], stats["units_skipped"]) == (2, 0)
    assert (stats["llm_finding_count"], stats["hallucination_count"], stats["intercept_rate"]) == (2, 1, 0.5)
    assert stats["rule_finding_count"] == sum(1 for f in data["findings"] if f["source"] == "rule") > 0

    # 编造的那条落库但不展示；展示出来的每一条都能在原文里逐字定位，并映射到了页码与坐标
    llm_shown = [f for f in data["findings"] if f["source"] == "llm"]
    assert [f["evidence_quote"] for f in llm_shown] == ["持续改进各项功能"]
    full_text = client.get(f"{API}/{rid}/blocks", headers=auth_headers).json()["data"]["full_text"]
    located = [f for f in data["findings"] if f["char_start"] is not None]
    assert located and all(full_text[f["char_start"]:f["char_end"]] == f["evidence_quote"] for f in located)
    assert all(f["page_no"] == 1 and len(f["bbox"]) == 4 for f in located)
    severities = [f["severity"] for f in data["findings"]]
    assert severities == sorted(severities, key=["high", "medium", "low"].index)

    with db_session_factory() as db:
        failed = db.query(Finding).filter_by(diagnosis_id=did, verify_result="failed").all()
        assert [f.evidence_quote for f in failed] == ["主导了整个公司的架构升级"]

    # 总分回写到简历，列表页直接可用
    assert data["overall_score"] is not None
    assert client.get(f"{API}/{rid}", headers=auth_headers).json()["data"]["overall_score"] == data["overall_score"]


def test_rule_only_and_lookup_by_id(client, auth_headers, resume_and_job, fake_llm):
    rid, jid = resume_and_job
    first = _diagnose(client, auth_headers, rid, jid, diagnose_mode="rule_only")
    assert not any(k.startswith("_ReviewOut") for k in fake_llm.calls)                           # 只跑规则，不调模型
    second = _diagnose(client, auth_headers, rid, jid)                                            # 默认 hybrid
    assert len(fake_llm.calls["_ReviewOut"]) == 2

    latest = client.get(f"{API}/{rid}/diagnosis", headers=auth_headers).json()["data"]
    assert (latest["id"], latest["mode"]) == (second, "hybrid")

    older = client.get(f"{API}/{rid}/diagnosis", headers=auth_headers, params={"diagnosis_id": first}).json()["data"]
    assert (older["id"], older["mode"]) == (first, "rule_only")
    assert older["stats"]["llm_finding_count"] == 0 and older["stats"]["intercept_rate"] is None and older["cost"] == 0


def test_cost_limit_gives_partial_status(client, auth_headers, resume_and_job, monkeypatch):
    rid, jid = resume_and_job
    monkeypatch.setattr(settings, "DIAGNOSE_COST_LIMIT", 0.004)          # 每单元预估 0.003 → 只够审 1 条
    _diagnose(client, auth_headers, rid, jid)
    data = client.get(f"{API}/{rid}/diagnosis", headers=auth_headers).json()["data"]
    assert data["status"] == "partial" and data["stats"]["units_skipped"] == 1 and data["overall_score"] is not None


def test_model_failure_marks_the_diagnosis_failed(client, auth_headers, resume_and_job, fake_llm):
    rid, jid = resume_and_job
    fake_llm.replies[f"_ReviewOut:{H_GOOD}"] = [LLMError("上游超时")]
    _diagnose(client, auth_headers, rid, jid)

    data = client.get(f"{API}/{rid}/diagnosis", headers=auth_headers).json()["data"]
    assert data["status"] == "failed" and "LLMError" in data["error_msg"] and data["findings"] == []
    assert client.get(f"{API}/{rid}", headers=auth_headers).json()["data"]["overall_score"] is None


def test_rejections(client, auth_headers, tmp_path, db_session_factory):
    rid = parsed_resume(client, auth_headers, tmp_path, db_session_factory)
    assert client.get(f"{API}/{rid}/diagnosis", headers=auth_headers).json()["code"] == 40401      # 还没诊断过
    assert client.get(f"{API}/{rid}/diagnosis").status_code == 401

    other = client.post("/api/v1/auth/register", json={"username": "someone_else", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['data']['access_token']}"}
    assert client.get(f"{API}/{rid}/diagnosis", headers=other_headers).json()["code"] == 40401     # 别人的简历
