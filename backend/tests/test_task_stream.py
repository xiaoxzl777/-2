"""SSE 进度流：假订阅预先排好消息；done / error 以数据库状态为准。"""
import json

import pytest

from app.api import task as task_api
from app.cache.pubsub import get_subscriber
from app.models import MatchReport, Resume
from tests.conftest import parsed_resume as _parsed_resume

API = "/api/v1/tasks"


class FakeSubscription:
    """按顺序吐出预设的消息；消息吐完后执行 on_drained（测试用它把任务改成已完成）。"""

    def __init__(self, messages, on_drained=None):
        self.messages, self.on_drained, self.closed = list(messages), on_drained, False

    def get(self, timeout):
        if self.messages:
            return self.messages.pop(0)
        if self.on_drained:
            self.on_drained()
            self.on_drained = None
        return None

    def close(self):
        self.closed = True


@pytest.fixture
def subscribe(client):
    """返回一个登记函数：subscribe.use(FakeSubscription(...)) 之后，接口拿到的就是它。"""
    from app.main import app

    holder = {"subscription": FakeSubscription([]), "task_ids": []}

    def factory(task_id):
        holder["task_ids"].append(task_id)
        return holder["subscription"]

    app.dependency_overrides[get_subscriber] = lambda: factory
    factory.use = lambda s: holder.__setitem__("subscription", s) or s
    factory.task_ids = holder["task_ids"]
    return factory


def _events(response) -> list[tuple[str, dict]]:
    out = []
    for chunk in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.split("\n") if not line.startswith(":"))
        if lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_finished_task_gets_done_immediately(client, auth_headers, tmp_path, db_session_factory, subscribe):
    rid = _parsed_resume(client, auth_headers, tmp_path, db_session_factory)
    sub = subscribe.use(FakeSubscription([{"event": "progress", "data": {"stage": "never delivered"}}]))

    r = client.get(f"{API}/parse/{rid}/stream", headers=auth_headers)
    assert r.headers["content-type"].startswith("text/event-stream") and r.headers["x-accel-buffering"] == "no"
    assert _events(r) == [("done", {"kind": "parse", "id": rid, "status": "success"})]
    assert subscribe.task_ids == [f"parse:{rid}"] and sub.closed                  # 连接结束后订阅一定被关掉


def test_progress_is_relayed_until_the_database_says_done(client, auth_headers, tmp_path, db_session_factory, subscribe):
    rid = _parsed_resume(client, auth_headers, tmp_path, db_session_factory)
    with db_session_factory() as db:
        report = MatchReport(resume_id=rid, job_id=1, status="running", mode="hybrid")
        db.add(report)
        db.commit()
        report_id = report.id

    def finish():
        with db_session_factory() as db:
            db.get(MatchReport, report_id).status = "success"
            db.commit()

    subscribe.use(FakeSubscription([
        {"event": "progress", "data": {"stage": "analyzing", "percent": 20}},
        {"event": "done", "data": {"ignored": True}},                              # 频道里的 done 不转发，以数据库为准
        {"event": "progress", "data": {"stage": "gate", "percent": 95}},
    ], on_drained=finish))

    events = _events(client.get(f"{API}/apply/{report_id}/stream", headers=auth_headers))
    assert events == [("progress", {"stage": "analyzing", "percent": 20}), ("progress", {"stage": "gate", "percent": 95}),
                      ("done", {"kind": "apply", "id": report_id, "status": "success"})]


def test_failed_task_gets_an_error_event(client, auth_headers, tmp_path, db_session_factory, subscribe):
    rid = _parsed_resume(client, auth_headers, tmp_path, db_session_factory)
    with db_session_factory() as db:
        failed = MatchReport(resume_id=rid, job_id=1, status="failed", mode="hybrid")
        db.add(failed)
        db.commit()
        failed_id = failed.id
    assert _events(client.get(f"{API}/apply/{failed_id}/stream", headers=auth_headers)) == [
        ("error", {"kind": "apply", "id": failed_id, "status": "failed"})]


def test_idle_streams_send_heartbeats_and_eventually_time_out(client, auth_headers, tmp_path, db_session_factory,
                                                              subscribe, monkeypatch):
    rid = _parsed_resume(client, auth_headers, tmp_path, db_session_factory)
    with db_session_factory() as db:
        db.get(Resume, rid).parse_status = "parsing"
        db.commit()

    clock = iter(range(0, 10_000, 10))                                             # 每看一次表走 10 秒
    monkeypatch.setattr(task_api.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(task_api, "MAX_STREAM_SECONDS", 100)

    r = client.get(f"{API}/parse/{rid}/stream", headers=auth_headers)
    assert ": keep-alive" in r.text
    assert _events(r)[-1] == ("error", {"kind": "parse", "id": rid, "status": "timeout"})


def test_rejections(client, auth_headers, tmp_path, db_session_factory, subscribe):
    rid = _parsed_resume(client, auth_headers, tmp_path, db_session_factory)
    assert client.get(f"{API}/backup/{rid}/stream", headers=auth_headers).json()["code"] == 40001
    assert client.get(f"{API}/match/{rid}/stream", headers=auth_headers).json()["code"] == 40001     # 匹配不再是单独的任务
    assert client.get(f"{API}/parse/9999/stream", headers=auth_headers).json()["code"] == 40401
    assert client.get(f"{API}/apply/9999/stream", headers=auth_headers).json()["code"] == 40401
    assert client.get(f"{API}/parse/{rid}/stream").status_code == 401

    other = client.post("/api/v1/auth/register", json={"username": "someone_else", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['data']['access_token']}"}
    assert client.get(f"{API}/parse/{rid}/stream", headers=other_headers).json()["code"] == 40401
    assert subscribe.task_ids == []                                                # 被拒绝的请求不会去订阅
