"""投递接口测试：一次请求跑完 诊断 + 匹配 + 初筛，验证两条记录的落库、进度事件、未通过说明。"""
from app.llm.client import LLMError
from app.models import Diagnosis, MatchReport
from tests.conftest import H_VAGUE, apply as _apply, fulltext_reply as _full, judge_reply as _judge, review_reply as _review

API = "/api/v1/apply"


def test_apply_runs_diagnosis_and_match_then_gates(client, auth_headers, resume_and_job, fake_llm, events):
    rid, jid = resume_and_job
    fake_llm.replies[f"_ReviewOut:{H_VAGUE}"] = [_review(("vague", "medium", "持续改进各项功能"))]
    fake_llm.replies["_JudgeOut:有缓存性能优化经验"] = [_judge("hit", 1)]
    fake_llm.replies["_JudgeOut:熟悉 Kafka"] = [_judge("miss")]
    fake_llm.replies["_FulltextOut"] = [_full((4, "miss", None))]

    started = _apply(client, auth_headers, rid, jid)["data"]
    assert started["task_id"] == f"apply:{started['id']}" and started["status"] == "pending" and started["diagnosis_id"]

    result = client.get(f"{API}/{started['id']}", headers=auth_headers).json()["data"]
    assert (result["status"], result["stage"], result["diagnosis_id"]) == ("success", "done", started["diagnosis_id"])
    assert result["gate"] == {"passed": True, "overall_match": round(100 * 2.5 / 3.5, 1), "threshold": 60.0}
    assert result["resume_score"] is not None and result["dimension_scores"]["education"] == 100.0

    # 哪里不符合：只有没满足的那条要求；简历自身的问题来自同一次投递的诊断
    assert [(g["requirement_id"], g["status"], g["content"]) for g in result["gaps"]] == [(4, "miss", "熟悉 Kafka")]
    assert result["resume_issues"] and "持续改进各项功能" in [f["evidence_quote"] for f in result["resume_issues"]]
    assert all(f["id"] for f in result["resume_issues"])                       # 带数据库 id，前端可以点开改写

    # 两份完整明细照常可查，并且互相关联
    match = client.get(f"/api/v1/match/{started['id']}", headers=auth_headers).json()["data"]
    assert match["status"] == "success" and match["diagnosis_id"] == started["diagnosis_id"] and len(match["items"]) == 4
    diagnosis = client.get(f"/api/v1/resumes/{rid}/diagnosis", headers=auth_headers,
                           params={"diagnosis_id": started["diagnosis_id"]}).json()["data"]
    assert diagnosis["status"] == "success" and diagnosis["job_title"] == "后端开发"    # 诊断时带上了目标岗位

    # 进度：解析 → 分析 → 两个并行分支各完成一次 → 初筛 → done
    assert {e[0] for e in events} == {f"apply:{started['id']}"}
    stages = [e[2].get("stage") for e in events if e[1] == "progress"]
    assert stages[:2] == ["parsing", "analyzing"] and sorted(stages[2:4]) == ["diagnose", "match"] and stages[4] == "gate"
    assert events[-1][1:] == ("done", {"id": started["id"], "status": "success", "passed": True})
    percents = [e[2]["percent"] for e in events if e[1] == "progress" and e[2]["stage"] not in ("diagnose", "match")]
    assert percents == sorted(percents)


def test_failed_gate_lists_gaps_by_importance(client, auth_headers, resume_and_job, fake_llm, events, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "SCREEN_THRESHOLD", 70.0)                 # 64.3 分过不了 70 分的线
    rid, jid = resume_and_job
    fake_llm.replies["_JudgeOut:有缓存性能优化经验"] = [_judge("partial", 1)]
    fake_llm.replies["_JudgeOut:熟悉 Kafka"] = [_judge("miss")]
    fake_llm.replies["_FulltextOut"] = [_full((4, "miss", None))]

    apply_id = _apply(client, auth_headers, rid, jid, diagnose_mode="rule_only")["data"]["id"]
    result = client.get(f"{API}/{apply_id}", headers=auth_headers).json()["data"]
    assert result["gate"]["passed"] is False and result["gate"]["overall_match"] == round(100 * 2.25 / 3.5, 1)
    # 必须项（权重 1.0）排在加分项（0.5）前面
    assert [(g["requirement_id"], g["status"], g["weight"]) for g in result["gaps"]] == [(4, "miss", 1.0), (3, "partial", 0.5)]
    assert events[-1][2]["passed"] is False


def test_a_failure_in_either_branch_fails_both_records(client, auth_headers, resume_and_job, fake_llm, events,
                                                        db_session_factory):
    rid, jid = resume_and_job
    fake_llm.replies["_JudgeOut:熟悉 Kafka"] = [LLMError("上游超时")]
    started = _apply(client, auth_headers, rid, jid)["data"]

    result = client.get(f"{API}/{started['id']}", headers=auth_headers).json()["data"]
    assert (result["status"], result["stage"], result["gate"], result["gaps"]) == ("failed", "failed", None, [])
    assert "LLMError" in result["error_msg"] and events[-1][1] == "error"
    with db_session_factory() as db:
        assert db.get(Diagnosis, started["diagnosis_id"]).status == "failed"
        assert db.get(MatchReport, started["id"]).status == "failed"
    # 失败不留"进行中"的记录，可以马上重试
    assert _apply(client, auth_headers, rid, jid, match_mode="dict_only", diagnose_mode="rule_only")["code"] == 0


def test_rejections(client, auth_headers, resume_and_job, db_session_factory, events):
    rid, jid = resume_and_job
    assert _apply(client, auth_headers, rid, jid, match_mode="fast")["code"] == 40001
    assert _apply(client, auth_headers, rid, jid, diagnose_mode="fast")["code"] == 40001
    assert _apply(client, auth_headers, rid, jid, model="gpt-99")["code"] == 40001
    assert _apply(client, auth_headers, 9999, jid)["code"] == 40401
    assert _apply(client, auth_headers, rid, 9999)["code"] == 40401
    assert client.post(API, json={"resume_id": rid, "job_id": jid}).status_code == 401
    assert client.get(f"{API}/9999", headers=auth_headers).json()["code"] == 40401

    other = client.post("/api/v1/auth/register", json={"username": "someone_else", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['data']['access_token']}"}
    apply_id = _apply(client, auth_headers, rid, jid, match_mode="dict_only", diagnose_mode="rule_only")["data"]["id"]
    assert client.get(f"{API}/{apply_id}", headers=other_headers).json()["code"] == 40401

    with db_session_factory() as db:                                       # 同一对简历-岗位已有投递在跑
        running = MatchReport(resume_id=rid, job_id=jid, status="running", mode="hybrid")
        db.add(running)
        db.commit()
    assert _apply(client, auth_headers, rid, jid)["code"] == 40901
    with db_session_factory() as db:
        db.query(MatchReport).filter_by(status="running").delete()
        db.commit()

    with db_session_factory() as db:                                       # 这份简历正在被诊断 → 不留下孤儿匹配记录
        db.add(Diagnosis(resume_id=rid, status="running", mode="hybrid"))
        db.commit()
        reports_before = db.query(MatchReport).count()
    assert _apply(client, auth_headers, rid, jid)["code"] == 40901
    with db_session_factory() as db:
        assert db.query(MatchReport).count() == reports_before
