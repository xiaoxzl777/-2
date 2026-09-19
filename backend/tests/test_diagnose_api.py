"""诊断接口测试：上传一份现场生成的 PDF，手工填好 structure（结构化抽取另有测试），用假模型跑完整条链路。"""
import json

from app.config import settings
from app.models import Diagnosis, Finding, Resume
from tests.conftest import make_pdf, upload_pdf

API = "/api/v1/resumes"
H_VAGUE = "1. 负责系统的优化工作，持续改进各项功能。"
H_GOOD = "2. 热点商品数据预热至 Redis，列表查询响应从 820ms 降至 140ms。"


def _parsed_resume(client, headers, tmp_path, db_session_factory) -> int:
    lines = [H_VAGUE, H_GOOD]
    items = [(40, 60, "Education", 12, "hebo"),                       # 凑够字数，否则会被判成扫描件
             (40, 80, "某某大学 计算机科学与技术 本科 2023.09-2027.06，主修数据结构、操作系统、计算机网络、数据库原理", 10.5, "china-s"),
             (40, 110, "Projects", 12, "hebo")]
    items += [(40, 140 + i * 20, t, 10.5, "china-s") for i, t in enumerate(lines)]
    rid = upload_pdf(client, headers, make_pdf(tmp_path / "r.pdf", items)).json()["data"]["id"]
    with db_session_factory() as db:
        resume = db.get(Resume, rid)
        hs = [{"text": t, "char_start": resume.full_text.index(t), "char_end": resume.full_text.index(t) + len(t)}
              for t in lines]
        resume.structure = {"projects": [{"name": "订单系统", "char_start": hs[0]["char_start"],
                                          "char_end": hs[-1]["char_end"], "highlights": hs}]}
        db.commit()
    return rid


def _reply(*items) -> str:
    return json.dumps({"findings": [
        {"risk_type": t, "severity": s, "evidence_quote": q, "reason": "r", "suggestion": "s"} for t, s, q in items]},
        ensure_ascii=False)


def test_diagnose_end_to_end(client, auth_headers, tmp_path, db_session_factory, fake_llm):
    rid = _parsed_resume(client, auth_headers, tmp_path, db_session_factory)
    fake_llm.replies[f"_ReviewOut:{H_VAGUE}"] = [
        _reply(("vague", "medium", "持续改进各项功能"), ("exaggeration", "high", "主导了整个公司的架构升级")),  # 第二条是编的
        _reply(),                                                                                        # 重试：放弃
    ]

    started = client.post(f"{API}/{rid}/diagnose", headers=auth_headers, json={"job_title": "后端开发"}).json()["data"]
    assert started["task_id"] == f"diagnose:{started['id']}" and started["status"] == "pending"

    # TestClient 在响应返回后同步跑完后台任务，此时诊断已结束
    data = client.get(f"{API}/{rid}/diagnosis", headers=auth_headers).json()["data"]
    assert (data["id"], data["status"], data["mode"], data["job_title"]) == (started["id"], "success", "hybrid", "后端开发")
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
        failed = db.query(Finding).filter_by(diagnosis_id=data["id"], verify_result="failed").all()
        assert [f.evidence_quote for f in failed] == ["主导了整个公司的架构升级"]

    # 总分回写到简历，列表页直接可用
    assert data["overall_score"] is not None
    assert client.get(f"{API}/{rid}", headers=auth_headers).json()["data"]["overall_score"] == data["overall_score"]


def test_rule_only_and_lookup_by_id(client, auth_headers, tmp_path, db_session_factory, fake_llm):
    rid = _parsed_resume(client, auth_headers, tmp_path, db_session_factory)
    first = client.post(f"{API}/{rid}/diagnose", headers=auth_headers, json={"mode": "rule_only"}).json()["data"]["id"]
    assert not any(k.startswith("_ReviewOut") for k in fake_llm.calls)                           # 只跑规则，不调模型
    second = client.post(f"{API}/{rid}/diagnose", headers=auth_headers).json()["data"]["id"]      # 不带请求体 = 默认 hybrid
    assert len(fake_llm.calls["_ReviewOut"]) == 2

    latest = client.get(f"{API}/{rid}/diagnosis", headers=auth_headers).json()["data"]
    assert (latest["id"], latest["mode"]) == (second, "hybrid")

    older = client.get(f"{API}/{rid}/diagnosis", headers=auth_headers, params={"diagnosis_id": first}).json()["data"]
    assert (older["id"], older["mode"]) == (first, "rule_only")
    assert older["stats"]["llm_finding_count"] == 0 and older["stats"]["intercept_rate"] is None and older["cost"] == 0


def test_cost_limit_gives_partial_status(client, auth_headers, tmp_path, db_session_factory, monkeypatch):
    rid = _parsed_resume(client, auth_headers, tmp_path, db_session_factory)
    monkeypatch.setattr(settings, "DIAGNOSE_COST_LIMIT", 0.004)          # 每单元预估 0.003 → 只够审 1 条
    client.post(f"{API}/{rid}/diagnose", headers=auth_headers)
    data = client.get(f"{API}/{rid}/diagnosis", headers=auth_headers).json()["data"]
    assert data["status"] == "partial" and data["stats"]["units_skipped"] == 1 and data["overall_score"] is not None


def test_model_failure_marks_the_diagnosis_failed(client, auth_headers, tmp_path, db_session_factory, fake_llm):
    from app.llm.client import LLMError

    rid = _parsed_resume(client, auth_headers, tmp_path, db_session_factory)
    fake_llm.replies[f"_ReviewOut:{H_GOOD}"] = [LLMError("上游超时")]
    client.post(f"{API}/{rid}/diagnose", headers=auth_headers)

    data = client.get(f"{API}/{rid}/diagnosis", headers=auth_headers).json()["data"]
    assert data["status"] == "failed" and "LLMError" in data["error_msg"] and data["findings"] == []
    assert client.get(f"{API}/{rid}", headers=auth_headers).json()["data"]["overall_score"] is None


def test_rejections(client, auth_headers, tmp_path, db_session_factory):
    rid = _parsed_resume(client, auth_headers, tmp_path, db_session_factory)
    url = f"{API}/{rid}/diagnose"

    assert client.get(f"{API}/{rid}/diagnosis", headers=auth_headers).json()["code"] == 40401      # 还没诊断过
    assert client.post(url, headers=auth_headers, json={"mode": "fast"}).json()["code"] == 40001
    assert client.post(url, headers=auth_headers, json={"model": "gpt-99"}).json()["code"] == 40001
    assert client.post(url).status_code == 401

    other = client.post("/api/v1/auth/register", json={"username": "someone_else", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['data']['access_token']}"}
    assert client.post(url, headers=other_headers).json()["code"] == 40401                           # 别人的简历
    assert client.get(f"{API}/{rid}/diagnosis", headers=other_headers).json()["code"] == 40401

    with db_session_factory() as db:                                                                 # 已有诊断在跑
        db.add(Diagnosis(resume_id=rid, status="running", mode="hybrid"))
        db.commit()
    assert client.post(url, headers=auth_headers).json()["code"] == 40901

    with db_session_factory() as db:                                                                 # 简历还在解析
        db.get(Resume, rid).parse_status = "parsing"
        db.commit()
    assert client.post(url, headers=auth_headers).json()["code"] == 40901
