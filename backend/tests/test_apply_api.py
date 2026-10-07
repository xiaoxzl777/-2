"""投递接口测试：一次请求跑完 诊断 + 匹配 + 初筛，验证两条记录的落库、进度事件、未通过说明。"""
from app.llm.client import LLMError
from app.models import Diagnosis, InterviewSession, MatchReport, Resume
from tests.conftest import H_VAGUE, apply as _apply, fulltext_reply as _full, review_reply as _review

API = "/api/v1/apply"


def test_apply_runs_diagnosis_and_match_then_gates(client, auth_headers, resume_and_job, fake_llm, events):
    rid, jid = resume_and_job
    fake_llm.replies[f"_ReviewOut:{H_VAGUE}"] = [_review(("vague", "medium", "持续改进各项功能"))]
    fake_llm.replies["_FulltextOut"] = [_full((3, "hit", "列表查询响应从 820ms 降至 140ms"), (4, "miss", None))]

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
    fake_llm.replies["_FulltextOut"] = [_full((3, "partial", "列表查询响应从 820ms 降至 140ms"), (4, "miss", None))]

    apply_id = _apply(client, auth_headers, rid, jid, diagnose_mode="rule_only")["data"]["id"]
    result = client.get(f"{API}/{apply_id}", headers=auth_headers).json()["data"]
    assert result["gate"]["passed"] is False and result["gate"]["overall_match"] == round(100 * 2.25 / 3.5, 1)
    # 必须项（权重 1.0）排在加分项（0.5）前面
    assert [(g["requirement_id"], g["status"], g["weight"]) for g in result["gaps"]] == [(4, "miss", 1.0), (3, "partial", 0.5)]
    assert events[-1][2]["passed"] is False


def test_a_failure_in_either_branch_fails_both_records(client, auth_headers, resume_and_job, fake_llm, events,
                                                        db_session_factory):
    rid, jid = resume_and_job
    fake_llm.replies["_FulltextOut"] = [LLMError("上游超时")]
    started = _apply(client, auth_headers, rid, jid)["data"]

    result = client.get(f"{API}/{started['id']}", headers=auth_headers).json()["data"]
    assert (result["status"], result["stage"], result["gate"], result["gaps"]) == ("failed", "failed", None, [])
    assert "LLMError" in result["error_msg"] and events[-1][1] == "error"
    with db_session_factory() as db:
        assert db.get(Diagnosis, started["diagnosis_id"]).status == "failed"
        assert db.get(MatchReport, started["id"]).status == "failed"
    # 失败不留"进行中"的记录，可以马上重试
    assert _apply(client, auth_headers, rid, jid, match_mode="dict_only", diagnose_mode="rule_only")["code"] == 0


def test_a_failure_while_saving_does_not_leave_records_running(client, auth_headers, resume_and_job, events,
                                                                db_session_factory, monkeypatch):
    from app.services import match_service

    def broken(*args, **kwargs):
        raise RuntimeError("写库失败")

    monkeypatch.setattr(match_service, "save_result", broken)
    rid, jid = resume_and_job
    started = _apply(client, auth_headers, rid, jid, match_mode="dict_only", diagnose_mode="rule_only")["data"]

    result = client.get(f"{API}/{started['id']}", headers=auth_headers).json()["data"]
    assert result["status"] == "failed" and "写库失败" in result["error_msg"] and events[-1][1] == "error"
    with db_session_factory() as db:
        assert db.get(Diagnosis, started["diagnosis_id"]).status == "failed"


def test_startup_cleanup_also_fails_applies_still_waiting_for_the_resume(client, auth_headers, resume_and_job,
                                                                         db_session_factory):
    """投递在等简历解析时服务重启：两条记录还是 pending，也要标成失败，否则这份简历再也投不了（一直 409）。"""
    from sqlalchemy import text

    from app.main import _CLEANUP_SQL

    rid, jid = resume_and_job
    with db_session_factory() as db:
        diagnosis = Diagnosis(resume_id=rid, status="pending", mode="hybrid")
        report = MatchReport(resume_id=rid, job_id=jid, status="pending", mode="hybrid")
        db.add_all([diagnosis, report])
        db.commit()
        for table in ("diagnoses", "match_reports"):
            db.execute(text(_CLEANUP_SQL[table]))
        db.commit()
        db.refresh(diagnosis)
        db.refresh(report)
        assert (diagnosis.status, report.status, report.error_msg) == ("failed", "failed", "interrupted")
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


def test_list_shows_my_applies_newest_first_with_their_interviews(client, auth_headers, resume_and_job, db_session_factory):
    """我的投递：新的在前；失败的给一句人话（不是技术报错）；面试挂在各自的投递下面；别人看不到，简历删了就不列。"""
    rid, jid = resume_and_job
    done_id = _apply(client, auth_headers, rid, jid, match_mode="dict_only", diagnose_mode="rule_only")["data"]["id"]
    with db_session_factory() as db:
        resume = db.get(Resume, rid)
        failed = MatchReport(resume_id=rid, job_id=jid, status="failed", error_msg="TimeoutError: 等待简历解析超时")
        db.add(failed)
        five = {"topics": [{"idx": i} for i in range(5)]}
        db.add_all([InterviewSession(user_id=resume.user_id, resume_id=rid, job_id=jid, match_report_id=done_id,
                                     mode="practice", status="completed", plan=five,
                                     report={"overall": 65, "verdict": "practice"}),
                    InterviewSession(user_id=resume.user_id, resume_id=rid, job_id=jid, match_report_id=done_id,
                                     mode="normal", status="in_progress", plan=five, current_topic=2)])
        db.commit()
        failed_id, title = failed.id, resume.title

    data = client.get(API, headers=auth_headers).json()["data"]
    assert data["total"] == 2 and [a["id"] for a in data["items"]] == [failed_id, done_id]
    newest, done = data["items"]
    assert (newest["status"], newest["passed"], newest["failure"], newest["interviews"]) ==         ("failed", None, "分析时出错了，可以再投一次", [])
    assert (done["status"], done["passed"], done["failure"]) == ("success", False, None) and done["overall_match"] > 0
    assert (done["job_title"], done["domain"], done["resume_id"], done["resume_title"]) == ("后端开发", "cs", rid, title)
    assert [(i["mode"], i["status"], i["current_topic"], i["topic_count"], i["overall"], i["verdict"])
            for i in done["interviews"]] == [("normal", "in_progress", 3, 5, None, None),      # 新的在前；话题从 1 数
                                             ("practice", "completed", 0, 5, 65, "practice")]
    page2 = client.get(API, headers=auth_headers, params={"page": 2, "page_size": 1}).json()["data"]
    assert (page2["total"], [a["id"] for a in page2["items"]]) == (2, [done_id])

    with db_session_factory() as db:                                    # 简历本身没解析出来：说清原因
        resume = db.get(Resume, rid)
        resume.parse_status, resume.parse_error = "failed", "scanned_pdf"
        db.commit()
    assert "扫描件" in client.get(API, headers=auth_headers).json()["data"]["items"][0]["failure"]

    other = client.post("/api/v1/auth/register", json={"username": "someone_else", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['data']['access_token']}"}
    assert client.get(API, headers=other_headers).json()["data"]["total"] == 0
    client.delete(f"/api/v1/resumes/{rid}", headers=auth_headers)
    assert client.get(API, headers=auth_headers).json()["data"] == {"items": [], "total": 0, "page": 1, "page_size": 20}
