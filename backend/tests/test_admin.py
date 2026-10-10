"""管理端：管理员账号与权限、模型用量统计、模型设置（对话模型换 Key / 换供应商，检索模型换向量 / 重排）。不联网：试连换成假的。"""
from datetime import date, datetime, time, timedelta

import httpx
import openai
import pytest
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI

from app.config import settings
from app.llm import provider, registry
from app.llm.embedding import EmbeddingClient
from app.llm.provider import Provider, Retrieval
from app.models import Finding, InterviewSession, Job, LlmCall, LlmProvider, MatchReport, Resume, User
from app.security import decrypt_secret, encrypt_secret
from app.services import admin_service, provider_service
from tests.conftest import apply as _apply
from tests.test_llm_client import MESSAGES, Harness

API = "/api/v1/admin"
KEY = "sk-test-key-0000000000001a2b"
RETRIEVAL = {"base_url": "https://api.siliconflow.cn/v1/", "api_key": KEY, "embed_model": "BAAI/bge-large-zh-v1.5",
             "rerank_model": "BAAI/bge-reranker-v2-m3"}
BAILIAN = {"kind": "bailian", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/", "model": "qwen-plus",
           "api_key": KEY, "price_in": 0.8, "price_out": 2}


@pytest.fixture
def admin_headers(client, db_session_factory) -> dict:
    with db_session_factory() as db:
        admin_service.ensure_admin(db)
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "88888888"})
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest.fixture
def conn(monkeypatch):
    """试连换成假的：conn.fail = "原因" 就算没连上；conn.tried 记下每次拿去试的配置；conn.forgot 记下横幅结论被清了几次；
    conn.dropped 记下向量库被清了几次（真的去清要打开 Chroma）。对话模型和检索模型的试连都换掉。"""
    class Conn:
        fail: str | None = None

    state = Conn()
    state.tried, state.forgot, state.dropped = [], [], []

    def fake_retrieval(r: Retrieval):
        state.tried.append(r)
        return (False, state.fail, None) if state.fail else (True, "连上了：向量 1024 维，重排正常，用时 0.9 秒", 900)

    monkeypatch.setattr(provider_service, "test_retrieval", fake_retrieval)
    monkeypatch.setattr(provider_service.context_store, "drop_all", lambda: state.dropped.append(1))

    def fake(p: Provider):
        state.tried.append(p)
        return (False, state.fail, None) if state.fail else (True, "连上了，回的 JSON 合格，用时 1.2 秒", 1200)

    monkeypatch.setattr(provider_service, "test_connection", fake)
    monkeypatch.setattr(provider_service.llm_status, "forget", lambda: state.forgot.append(1))
    return state


# ───────────── 账号与权限 ─────────────


def test_admin_account_is_created_once_and_its_name_is_reserved(client, db_session_factory):
    with db_session_factory() as db:
        admin_service.ensure_admin(db)
        admin_service.ensure_admin(db)                                     # 再启动一次：不会建第二个
        assert [(u.username, u.role) for u in db.query(User).all()] == [("admin", "admin")]
    login = lambda password: client.post("/api/v1/auth/login", json={"username": "admin", "password": password}).json()   # noqa: E731
    token = login("88888888")
    assert token["code"] == 0 and token["data"]["user"]["role"] == "admin"

    headers = {"Authorization": f"Bearer {token['data']['access_token']}"}
    changed = client.post("/api/v1/auth/password", headers=headers, json={"old_password": "88888888", "new_password": "new-secret-1"})
    assert changed.json()["code"] == 0
    with db_session_factory() as db:
        admin_service.ensure_admin(db)                                     # 重启不会把改过的密码改回默认的
    assert login("88888888")["code"] == 40101 and login("new-secret-1")["code"] == 0

    for name in ("admin", "Admin"):                                        # 这个用户名别人注册不了
        r = client.post("/api/v1/auth/register", json={"username": name, "password": "secret123"}).json()
        assert (r["code"], r["message"]) == (40901, "用户名或邮箱已被注册")


def test_a_seeker_already_named_admin_is_not_promoted(db_session_factory):
    """加这个功能之前就有人注册了 admin：不能替他升成管理员，那等于把管理端交给注册的人。"""
    with db_session_factory() as db:
        db.add(User(username="admin", password_hash="x"))
        db.commit()
        admin_service.ensure_admin(db)
        assert [(u.username, u.role) for u in db.query(User).all()] == [("admin", "seeker")]


def test_admin_endpoints_need_the_admin_role(client, auth_headers, admin_headers, conn):
    calls = [("get", "/usage", None), ("get", "/providers", None), ("get", "/providers/status", None),
             ("post", "/providers/test", BAILIAN), ("post", "/providers/0/test", None), ("post", "/providers", BAILIAN),
             ("put", "/providers/0/key", {"api_key": KEY}), ("post", "/providers/0/activate", None), ("delete", "/providers/1", None),
             ("get", "/retrieval", None), ("get", "/retrieval/status", None), ("post", "/retrieval/test", None),
             ("put", "/retrieval", RETRIEVAL), ("delete", "/retrieval", None)]
    for method, path, body in calls:
        send = lambda headers: client.request(method, API + path, headers=headers, json=body)      # noqa: E731, B023
        assert send({}).status_code == 401, path
        refused = send(auth_headers)                                       # 普通用户：403，不是 401（前端收到 401 会直接退出登录）
        assert (refused.status_code, refused.json()["code"], refused.json()["message"]) == (403, 40301, "需要管理员权限"), path
    assert provider.current().id is None and provider.retrieval().from_env and conn.tried == []   # 被拒绝的请求什么都没动
    assert client.get(f"{API}/providers", headers=admin_headers).json()["code"] == 0


# ───────────── 模型用量 ─────────────


@pytest.fixture
def usage_data(client, auth_headers, resume_and_job, db_session_factory):
    """两个用户的调用记录，日期按「今天往前数几天」定。返回 (今天, 两个用户的 id)。"""
    today = date.today()
    at = lambda days_ago: datetime.combine(today - timedelta(days=days_ago), time(12))           # noqa: E731
    rid, jid = resume_and_job
    aid = _apply(client, auth_headers, rid, jid, match_mode="dict_only", diagnose_mode="rule_only")["data"]["id"]
    other_id = client.post("/api/v1/auth/register", json={"username": "someone_else", "password": "secret123"}).json()["data"]["user"]["id"]

    with db_session_factory() as db:
        report = db.get(MatchReport, aid)
        mine = db.get(Resume, rid)
        fid = db.query(Finding).filter_by(diagnosis_id=report.diagnosis_id).first().id
        theirs = Resume(user_id=other_id, title="r2.pdf", file_path="uploads/x.pdf", file_type="pdf", file_size=1, file_hash="0" * 64)
        db.add(theirs)
        db.flush()
        interview = InterviewSession(user_id=other_id, resume_id=theirs.id, job_id=jid, match_report_id=aid, mode="practice",
                                     status="completed", plan={"topics": []})
        db.add(interview)
        db.flush()
        for row in (mine, report, theirs, interview):                      # SQLite 的 now() 是 UTC：把这几条的时间定成今天
            row.created_at = at(0)

        def call(scene, ref, days_ago, tin=0, tout=0, cost=0.0, **extra):
            db.add(LlmCall(scene=scene, ref_type=ref and ref[0], ref_id=ref and ref[1], provider="deepseek", model_name="deepseek-chat",
                           token_input=tin, token_output=tout, cost=cost, created_at=at(days_ago), **extra))

        diagnosis = ("diagnosis", report.diagnosis_id)
        call("diagnose", diagnosis, 0, 300, 30, 0.002)
        call("diagnose", diagnosis, 0, cache_hit=True)                     # 命中缓存：记次数，不花钱
        call("diagnose", diagnosis, 0, success=False, error_msg="APITimeoutError")
        call("match", ("match_report", aid), 0, 400, 200, 0.004)
        call("structure", ("resume", rid), 2, 200, 60, 0.0016)
        call("jd_parse", ("job", jid), 2, 240, 190, 0.003)
        call("rewrite", ("finding", fid), 2, 430, 120, 0.003)
        call("something_new", ("resume", rid), 2, 10, 5, 0.0001)           # 以后新加的场景：归到「其他」，不丢
        call("interview_ask", ("interview", interview.id), 2, 500, 100, 0.0035)
        call("embed", ("interview", interview.id), 2, 50, 0, 0.0)
        call("diagnose", ("diagnosis", 99999), 2, 100, 10, 0.001)          # 挂着的对象已经不在了
        call("gap", ("match_report", aid), 10, 400, 100, 0.003)            # 十天前：7 天的范围外
        call("diagnose", diagnosis, 1, 900, 90, 0.01, run_id="run-1")      # 评测批次：不算用户的
        call("structure", None, 1, 5000, 900, 0.5)                         # 脚本跑的：没有挂对象
        db.commit()
        tester_id = mine.user_id
    return today, tester_id, other_id


def test_usage_counts_only_user_calls_by_day_feature_and_user(db_session_factory, usage_data):
    today, tester_id, other_id = usage_data
    with db_session_factory() as db:
        u = admin_service.usage(db, 7, today=today)

    assert u["total"] == {"calls": 11, "cached": 1, "failed": 1, "token_input": 2230, "token_output": 715, "cost": pytest.approx(0.0182)}
    assert (u["window_cost"], u["today_cost"]) == (pytest.approx(0.0182), pytest.approx(0.006))
    assert (u["other_calls"], u["other_cost"], u["registered"]) == (2, pytest.approx(0.51), 2)   # 评测 + 脚本另算

    days = {d["date"]: (d["calls"], d["cost"]) for d in u["by_day"]}
    assert list(days) == [today - timedelta(days=n) for n in range(6, -1, -1)]                    # 没有调用的日子也占一格
    assert days[today] == (4, pytest.approx(0.006)) and days[today - timedelta(days=2)] == (7, pytest.approx(0.0122))
    assert sum(calls for calls, _ in days.values()) == 11

    assert [(f["name"], f["calls"], f["cost"]) for f in u["features"]] == [
        ("简历解析", 1, pytest.approx(0.0016)), ("岗位解析", 1, pytest.approx(0.003)), ("诊断", 4, pytest.approx(0.003)),
        ("匹配", 1, pytest.approx(0.004)), ("具体建议", 1, pytest.approx(0.003)), ("模拟面试", 2, pytest.approx(0.0035)),
        ("其他", 1, pytest.approx(0.0001))]
    diagnose = next(f for f in u["features"] if f["key"] == "diagnose")
    assert (diagnose["cached"], diagnose["failed"]) == (1, 1)

    # 每种对象都认得出是谁的：诊断、投递、建议（挂在问题上）、简历、岗位、面试
    tester, other, gone = u["users"]
    assert (tester["user_id"], tester["username"], tester["calls"], tester["failed"], tester["cost"]) ==         (tester_id, "tester", 8, 1, pytest.approx(0.0137))
    assert (tester["resumes"], tester["applies"], tester["interviews"], tester["last_used"]) == (1, 1, 0, today)
    assert (other["user_id"], other["username"], other["calls"], other["cost"]) == (other_id, "someone_else", 2, pytest.approx(0.0035))
    assert (other["resumes"], other["applies"], other["interviews"], other["last_used"]) == (1, 0, 1, today - timedelta(days=2))
    assert (gone["user_id"], gone["username"], gone["calls"], gone["cost"]) == (None, None, 1, pytest.approx(0.001))

    # 最近失败：只有用户的那一次（评测、脚本里失败的不算），带上是谁的、哪个功能、归好类的原因
    assert [(f["feature"], f["username"], f["reason"], f["detail"], f["at"].date()) for f in u["failures"]] == \
        [("诊断", "tester", "超时", "APITimeoutError", today)]


def test_usage_window_and_single_day(db_session_factory, usage_data):
    today, tester_id, _ = usage_data
    two_days_ago, ten_days_ago = today - timedelta(days=2), today - timedelta(days=10)
    with db_session_factory() as db:
        month = admin_service.usage(db, 30, today=today)
        assert month["total"]["calls"] == 12 and len(month["by_day"]) == 30
        assert next(f for f in month["features"] if f["key"] == "advice")["calls"] == 2

        whole = admin_service.usage(db, 0, today=today)                    # 全部：从第一条用户调用那天起
        assert whole["by_day"][0]["date"] == ten_days_ago and len(whole["by_day"]) == 11 and whole["total"]["calls"] == 12

        one = admin_service.usage(db, 7, day=two_days_ago, today=today)    # 只看一天：四个数和两张表只算它，图还是整段
        assert (one["day"], one["total"]["calls"], one["total"]["cost"]) == (two_days_ago, 7, pytest.approx(0.0122))
        assert one["window_cost"] == pytest.approx(0.0182) and len(one["by_day"]) == 7
        assert [f["calls"] for f in one["features"] if f["key"] in ("diagnose", "match")] == [1, 0]
        tester = next(x for x in one["users"] if x["user_id"] == tester_id)
        assert (tester["calls"], tester["cost"], tester["last_used"]) == (4, pytest.approx(0.0077), two_days_ago)
        assert (tester["resumes"], tester["applies"]) == (0, 0)            # 简历和投递是今天的，不算在那一天
        assert one["failures"] == [] and len(month["failures"]) == 1       # 失败的那次是今天的：只看前天就没有

        assert admin_service.usage(db, 7, day=ten_days_ago, today=today)["day"] is None           # 不在图的范围里：当没选

        quiet = admin_service.usage(db, 7, today=today + timedelta(days=60))                       # 一条调用都没有的一段
        assert quiet["total"]["calls"] == 0 and quiet["users"] == [] and quiet["features"][0]["calls"] == 0


@pytest.mark.parametrize("error_msg, reason", [
    ("APIStatusError: Error code: 402 - {'error': {'message': 'Insufficient Balance (request_id: x)'}}", "余额不足（402）"),
    ("AuthenticationError: Error code: 401 - {'error': {'message': 'Authentication Fails'}}", "密钥无效（401）"),
    ("RateLimitError: Error code: 429 - {}", "请求太快，被服务商限流（429）"),
    ("NotFoundError: Error code: 404 - {}", "接口地址或模型名不对（404）"),
    ("BadRequestError: Error code: 400 - {'message': 'Model does not exist'}", "请求被拒绝（400），多半是模型名不对"),
    ("InternalServerError: Error code: 503 - {}", "模型服务自己出错了（503）"),
    ("HTTPStatusError: Client error '401 Unauthorized' for url 'https://api.siliconflow.cn/v1/embeddings'", "密钥无效（401）"),   # 向量 / 重排走 httpx，报错长得不一样
    ("HTTPStatusError: Server error '502 Bad Gateway' for url 'https://x'", "模型服务自己出错了（502）"),
    ("APITimeoutError: Request timed out.", "超时"),
    ("ConnectTimeout: timed out", "超时"),
    ("APIConnectionError: Connection error.", "连不上模型服务"),
    ("限流占位失败：RateLimitTimeout: deepseek 限流等待超时", "排队等名额超时，或者 Redis 连不上"),
    ("调用方提前结束了流式读取", "页面中途关了或刷新了，没生成完"),
    ("ValueError: something odd", "其他错误"),
    (None, "其他错误"),
])
def test_failures_are_explained_in_plain_words(error_msg, reason):
    assert admin_service.failure_reason(error_msg) == reason


def test_recent_failures_are_capped_newest_first_and_never_show_a_key(db_session_factory, usage_data):
    today, _, _ = usage_data
    with db_session_factory() as db:
        rid = db.query(Resume).first().id
        fake_key = "sk-" + "abcdef1234567890XYZ"       # 编的。拼起来写：整串写在一起会被提交前的密钥扫描拦下
        for minute in range(25):
            db.add(LlmCall(scene="structure", ref_type="resume", ref_id=rid, provider="deepseek", model_name="deepseek-chat", success=False,
                           error_msg=f"AuthenticationError: Error code: 401 - key {fake_key}{minute:02d} is invalid",
                           created_at=datetime.combine(today, time(13, minute))))
        db.commit()
        failures = admin_service.usage(db, 7, today=today)["failures"]
    assert len(failures) == admin_service.FAILURES_SHOWN == 20                   # 多了只列最近的
    assert [f["at"].minute for f in failures[:3]] == [24, 23, 22] and failures[0]["feature"] == "简历解析"
    assert all("sk-abcdef" not in f["detail"] and "sk-…" in f["detail"] for f in failures)      # 报错里夹着的 Key 盖掉再给


def test_usage_endpoint(client, admin_headers, usage_data):
    data = client.get(f"{API}/usage", headers=admin_headers).json()["data"]
    assert (data["days"], data["day"], data["total"]["calls"], data["registered"]) == (7, None, 11, 2)   # 管理员自己不算注册用户
    assert [u["username"] for u in data["users"]] == ["tester", "someone_else", None]
    assert [(f["feature"], f["username"], f["reason"]) for f in data["failures"]] == [("诊断", "tester", "超时")]
    day = str(usage_data[0] - timedelta(days=2))
    assert client.get(f"{API}/usage", headers=admin_headers, params={"days": 30, "day": day}).json()["data"]["total"]["calls"] == 7
    assert client.get(f"{API}/usage", headers=admin_headers, params={"days": 5}).json()["code"] == 40001


# ───────────── 模型设置 ─────────────


def test_the_env_provider_is_used_until_one_is_switched_on(client, admin_headers, conn, monkeypatch):
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "sk-env-key-00000000000000009f3c")
    listed = client.get(f"{API}/providers", headers=admin_headers)
    data = listed.json()["data"]
    assert data["others"] == [] and data["current"] == {
        "id": 0, "kind": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "model": "deepseek-chat",
        "key_hint": "sk-••••••••9f3c", "price_in": 4.0, "price_out": 12.0, "active": True, "from_env": True, "key_ok": True}
    assert "sk-env-key" not in listed.text                                 # 完整的 Key 不出现在任何响应里
    assert [p["key"] for p in data["presets"]][:2] == ["deepseek", "siliconflow"] and data["presets"][-1]["key"] == "custom"


def test_a_provider_is_saved_only_if_it_connects_and_its_key_is_stored_encrypted(client, admin_headers, conn, db_session_factory):
    tested = client.post(f"{API}/providers/test", headers=admin_headers, json=BAILIAN).json()["data"]
    assert tested == {"ok": True, "message": "连上了，回的 JSON 合格，用时 1.2 秒", "latency_ms": 1200}
    assert (conn.tried[0].base_url, conn.tried[0].api_key, conn.tried[0].name) == \
        ("https://dashscope.aliyuncs.com/compatible-mode/v1", KEY, "阿里云百炼")                   # 末尾的斜杠去掉；名字取预设的

    conn.fail = "密钥无效（401）"
    refused = client.post(f"{API}/providers", headers=admin_headers, json=BAILIAN).json()
    assert (refused["code"], refused["message"]) == (40001, "密钥无效（401），没有保存")
    with db_session_factory() as db:
        assert db.query(LlmProvider).count() == 0

    conn.fail = None
    saved = client.post(f"{API}/providers", headers=admin_headers, json=BAILIAN)
    row = saved.json()["data"]
    assert (row["name"], row["model"], row["key_hint"], row["active"], row["price_out"]) == ("阿里云百炼", "qwen-plus", "sk-••••••••1a2b", False, 2.0)
    assert KEY not in saved.text and KEY not in client.get(f"{API}/providers", headers=admin_headers).text
    with db_session_factory() as db:
        stored = db.query(LlmProvider).one()
        assert KEY not in stored.api_key_enc and decrypt_secret(stored.api_key_enc) == KEY
    assert provider.current().id is None                                   # 存下来不等于启用

    for bad in ({"kind": "nobody"}, {"base_url": "ftp://x.example.com"}, {"model": ""}, {"api_key": "short"}, {"price_in": -1}):
        assert client.post(f"{API}/providers", headers=admin_headers, json={**BAILIAN, **bad}).json()["code"] == 40001, bad


def test_switching_provider_takes_effect_at_once(client, auth_headers, admin_headers, conn, resume_and_job, db_session_factory):
    pid = client.post(f"{API}/providers", headers=admin_headers, json=BAILIAN).json()["data"]["id"]

    conn.fail = "连不上模型服务（APIConnectionError）"                       # 切换前也要试：连不上就不换
    failed = client.post(f"{API}/providers/{pid}/activate", headers=admin_headers).json()
    assert (failed["code"], failed["message"]) == (40001, "连不上模型服务（APIConnectionError），没有切换")
    assert provider.current().model == "deepseek-chat" and conn.forgot == []

    conn.fail = None
    assert client.post(f"{API}/providers/{pid}/activate", headers=admin_headers).json()["code"] == 0
    now = provider.current()
    assert (now.id, now.kind, now.model, now.api_key, now.is_deepseek) == (pid, "bailian", "qwen-plus", KEY, False)
    assert conn.forgot == [1]                                              # 「模型服务不可用」的旧结论作废
    assert registry.available_models() == ["qwen-plus"] and registry.provider_of("qwen-plus") == "bailian"
    assert registry.estimate_cost("qwen-plus", 1_000_000, 1_000_000) == pytest.approx(2.8)        # 花费按这一家的单价估

    # 调模型的唯一出口跟着换：默认模型、限流分桶、审计里记的都是新的这一家
    h = Harness(['{"verdict": "ok", "score": 1}'])
    r = h.client.invoke("diagnose", MESSAGES, prompt_version="v1")
    assert (r.model, h.acquired, h.audits[0]["provider"], h.audits[0]["model_name"]) == ("qwen-plus", ["bailian"], "bailian", "qwen-plus")
    assert r.cost == pytest.approx((1000 * 0.8 + 500 * 2) / 1_000_000)
    # 新的投递记下的也是新模型
    rid, jid = resume_and_job
    aid = _apply(client, auth_headers, rid, jid, match_mode="dict_only", diagnose_mode="rule_only")["data"]["id"]
    with db_session_factory() as db:
        assert db.get(MatchReport, aid).model_name == "qwen-plus"

    listed = client.get(f"{API}/providers", headers=admin_headers).json()["data"]
    assert (listed["current"]["id"], listed["current"]["active"]) == (pid, True)
    assert [(o["id"], o["from_env"], o["active"]) for o in listed["others"]] == [(0, True, False)]  # .env 那一家还在，可以换回去

    in_use = client.delete(f"{API}/providers/{pid}", headers=admin_headers).json()
    assert (in_use["code"], in_use["message"]) == (40901, "正在用的这一条不能删，先换成别的")
    assert client.post(f"{API}/providers/0/activate", headers=admin_headers).json()["code"] == 0   # 换回 .env 那一家
    assert provider.current().id is None
    with db_session_factory() as db:
        assert db.query(LlmProvider).filter_by(is_active=True).count() == 0
    assert client.delete(f"{API}/providers/{pid}", headers=admin_headers).json()["code"] == 0
    assert client.delete(f"{API}/providers/{pid}", headers=admin_headers).json()["code"] == 40401
    assert client.delete(f"{API}/providers/0", headers=admin_headers).json()["code"] == 40401      # .env 那一家删不了


def test_changing_a_key_tests_the_new_one_first(client, admin_headers, conn, db_session_factory):
    new_key = "sk-new-key-0000000000000009e2d"
    pid = client.post(f"{API}/providers", headers=admin_headers, json=BAILIAN).json()["data"]["id"]
    client.post(f"{API}/providers/{pid}/activate", headers=admin_headers)

    conn.fail = "密钥无效（401）"
    refused = client.put(f"{API}/providers/{pid}/key", headers=admin_headers, json={"api_key": new_key}).json()
    assert (refused["code"], refused["message"]) == (40001, "密钥无效（401），没有改动")
    assert conn.tried[-1].api_key == new_key and provider.current().api_key == KEY                # 试的是新的；用的还是旧的

    conn.fail = None
    assert client.put(f"{API}/providers/{pid}/key", headers=admin_headers, json={"api_key": f"  {new_key} "}).json()["code"] == 0
    assert provider.current().api_key == new_key                           # 正在用的这一条：马上换上
    assert client.get(f"{API}/providers", headers=admin_headers).json()["data"]["current"]["key_hint"] == "sk-••••••••9e2d"


def test_changing_the_env_key_saves_a_copy_and_switches_to_it(client, admin_headers, conn, db_session_factory):
    """.env 那一家的 Key 在文件里，页面改不了：照它的配置在库里存一条带新 Key 的，并换过去。"""
    assert client.put(f"{API}/providers/0/key", headers=admin_headers, json={"api_key": KEY}).json()["code"] == 0
    now = provider.current()
    assert (now.id is not None, now.kind, now.model, now.base_url, now.api_key, now.is_deepseek) == \
        (True, "deepseek", "deepseek-chat", "https://api.deepseek.com", KEY, True)
    with db_session_factory() as db:
        assert db.query(LlmProvider).filter_by(is_active=True).count() == 1


def test_a_key_that_can_no_longer_be_read_falls_back_to_env(client, admin_headers, conn, db_session_factory):
    """JWT_SECRET 换过，库里的 Key 解不开：不让启用，服务退回 .env 那一家；重新填 Key 就好了。"""
    with db_session_factory() as db:
        db.add(LlmProvider(kind="zhipu", name="智谱", base_url="https://open.bigmodel.cn/api/paas/v4", model="glm-4-plus",
                           api_key_enc=encrypt_secret(KEY)[:-6] + "abcdef", key_hint="sk-••••••••1a2b", price_in=1, price_out=1,
                           is_active=True))
        db.commit()
        assert provider.load(db).id is None                                # 启动时读到它：退回 .env，不报错
        pid = db.query(LlmProvider).one().id
    assert client.get(f"{API}/providers", headers=admin_headers).json()["data"]["others"][0]["key_ok"] is False
    stuck = client.post(f"{API}/providers/{pid}/activate", headers=admin_headers).json()
    assert stuck["code"] == 40001 and "请先给它换 Key" in stuck["message"]
    assert client.put(f"{API}/providers/{pid}/key", headers=admin_headers, json={"api_key": KEY}).json()["code"] == 0
    assert client.post(f"{API}/providers/{pid}/activate", headers=admin_headers).json()["code"] == 0
    assert provider.current().model == "glm-4-plus"


def test_secrets_round_trip_and_do_not_open_with_another_secret(monkeypatch):
    from app import security

    token = encrypt_secret(KEY)
    assert token != KEY and decrypt_secret(token) == KEY and decrypt_secret("not-a-token") is None
    monkeypatch.setattr(settings, "JWT_SECRET", "another-secret")
    security._fernet.cache_clear()
    try:
        assert decrypt_secret(token) is None
    finally:
        monkeypatch.undo()
        security._fernet.cache_clear()


# ───────────── 试连、建模型（不发请求）─────────────


def test_deepseek_keeps_its_own_client_and_others_use_the_openai_compatible_one():
    deepseek = registry.build_chat_model(provider.env_provider(), 0.0)
    other = registry.build_chat_model(Provider(7, "bailian", "阿里云百炼", "https://dashscope.aliyuncs.com/compatible-mode/v1",
                                               "qwen-plus", KEY, 0.8, 2.0), 0.3)
    assert isinstance(deepseek, ChatDeepSeek) and deepseek.model_name == "deepseek-chat"
    assert isinstance(other, ChatOpenAI) and not isinstance(other, ChatDeepSeek)
    assert (other.model_name, other.openai_api_base, other.temperature) == ("qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1", 0.3)
    with pytest.raises(ValueError, match="现在用的是 deepseek-chat"):
        registry.get_chat_model("qwen-plus", 0.0)


class _FakeChat:
    def __init__(self, reply):
        self.reply, self.bound = reply, None

    def bind(self, **kwargs):
        self.bound = kwargs
        return self

    def invoke(self, messages):
        if isinstance(self.reply, Exception):
            raise self.reply
        return type("Reply", (), {"content": self.reply})()


def _status_error(code: int) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://example.com/chat/completions")
    return openai.APIStatusError("error", response=httpx.Response(code, request=request), body=None)


@pytest.mark.parametrize("reply, passed, says", [
    ('{"ok": true}', True, "连上了，回的 JSON 合格"),
    ('```json\n{"ok": true}\n```', True, "连上了"),
    ("好的，已收到。", False, "不支持 JSON 输出"),                          # 连得上但不会按 JSON 回：诊断和匹配用不了，挡在外面
    (_status_error(401), False, "密钥无效（401）"),
    (_status_error(402), False, "余额不足（402）"),
    (_status_error(404), False, "接口地址或模型名不对（404）"),
    (_status_error(400), False, "这家拒绝了请求（400）"),
    (openai.APIConnectionError(request=httpx.Request("POST", "https://example.com")), False, "连不上模型服务"),
    (RuntimeError("boom"), False, "调用出错（RuntimeError）"),
])
def test_connection_check_says_what_went_wrong(monkeypatch, reply, passed, says):
    chat = _FakeChat(reply)
    built = {}

    def build(p, temperature, **kwargs):
        built.update(kwargs, provider=p)
        return chat

    monkeypatch.setattr(registry, "build_chat_model", build)
    ok, message, ms = provider_service.test_connection(provider.env_provider())
    assert ok is passed and says in message and (ms is not None) == (not isinstance(reply, Exception))
    assert built["max_retries"] == 0 and built["timeout"] == provider_service.TEST_TIMEOUT    # 有人等着：不重试、超时短
    assert chat.bound == {"response_format": {"type": "json_object"}}                          # 和线上一样用 JSON 模式试


# ───────────── 检索模型（向量 + 重排）─────────────


def test_retrieval_uses_env_until_changed_and_changing_it_takes_effect_at_once(client, admin_headers, conn, db_session_factory, monkeypatch):
    monkeypatch.setattr(settings, "SILICONFLOW_API_KEY", "sk-env-sf-000000000000000007c2e")
    shown = client.get(f"{API}/retrieval", headers=admin_headers)
    assert shown.json()["data"] == {"from_env": True, "name": "硅基流动", "base_url": "https://api.siliconflow.cn/v1",
                                    "key_hint": "sk-••••••••7c2e", "embed_model": "BAAI/bge-m3", "rerank_model": "BAAI/bge-reranker-v2-m3"}
    assert "sk-env-sf" not in shown.text

    assert client.post(f"{API}/retrieval/test", headers=admin_headers).json()["data"]["ok"] is True      # 不带请求体：试现在用的
    assert (conn.tried[-1].from_env, conn.tried[-1].embed_model) == (True, "BAAI/bge-m3")
    client.post(f"{API}/retrieval/test", headers=admin_headers, json={**RETRIEVAL, "api_key": None})
    assert (conn.tried[-1].base_url, conn.tried[-1].api_key, conn.tried[-1].embed_model) == \
        ("https://api.siliconflow.cn/v1", "sk-env-sf-000000000000000007c2e", "BAAI/bge-large-zh-v1.5")    # Key 留空：用现在的那把

    conn.fail = "向量模型被拒绝了（400），多半是模型名不对"
    refused = client.put(f"{API}/retrieval", headers=admin_headers, json=RETRIEVAL).json()
    assert (refused["code"], refused["message"]) == (40001, "向量模型被拒绝了（400），多半是模型名不对，没有保存")
    assert provider.retrieval().from_env and conn.dropped == []

    conn.fail = None
    saved = client.put(f"{API}/retrieval", headers=admin_headers, json=RETRIEVAL)
    assert saved.json()["data"] == {"from_env": False, "name": "硅基流动", "base_url": "https://api.siliconflow.cn/v1",
                                    "key_hint": "sk-••••••••1a2b", "embed_model": "BAAI/bge-large-zh-v1.5",
                                    "rerank_model": "BAAI/bge-reranker-v2-m3"}
    assert KEY not in saved.text and conn.dropped == [1]                   # 向量模型换了：存着的面经切段清掉
    with db_session_factory() as db:
        row = db.query(LlmProvider).one()
        assert (row.purpose, row.model, row.rerank_model, decrypt_secret(row.api_key_enc)) == \
            ("retrieval", "BAAI/bge-large-zh-v1.5", "BAAI/bge-reranker-v2-m3", KEY)

    # 向量 / 重排的唯一出口马上用上新的：地址、Key、模型名
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        seen.append((str(request.url), request.headers["authorization"], json.loads(request.content)["model"]))
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}], "results": [{"index": 0, "relevance_score": 0.5}]})

    audits = []
    embedder = EmbeddingClient(http=httpx.Client(transport=httpx.MockTransport(handler)), acquire=lambda *_: None, write_audit=audits.append)
    embedder.embed(["面经"])
    embedder.rerank("问题", ["甲", "乙"], top_n=1)
    assert seen == [("https://api.siliconflow.cn/v1/embeddings", f"Bearer {KEY}", "BAAI/bge-large-zh-v1.5"),
                    ("https://api.siliconflow.cn/v1/rerank", f"Bearer {KEY}", "BAAI/bge-reranker-v2-m3")]
    assert [(a["provider"], a["model_name"]) for a in audits] == [("siliconflow", "BAAI/bge-large-zh-v1.5"), ("siliconflow", "BAAI/bge-reranker-v2-m3")]

    # 只换重排模型或 Key：向量还是那个模型算的，不用清
    client.put(f"{API}/retrieval", headers=admin_headers, json={**RETRIEVAL, "rerank_model": "netease-youdao/bce-reranker-base_v1", "api_key": ""})
    assert provider.retrieval().rerank_model == "netease-youdao/bce-reranker-base_v1" and provider.retrieval().api_key == KEY
    assert conn.dropped == [1]
    with db_session_factory() as db:
        assert db.query(LlmProvider).count() == 1                          # 只有一份：改就是换掉原来那一行

    back = client.delete(f"{API}/retrieval", headers=admin_headers).json()["data"]                 # 换回 .env：向量模型又变了，再清一次
    assert back["from_env"] is True and provider.retrieval().embed_model == "BAAI/bge-m3" and conn.dropped == [1, 1]
    for bad in ({"base_url": "siliconflow.cn"}, {"embed_model": ""}, {"rerank_model": ""}):
        assert client.put(f"{API}/retrieval", headers=admin_headers, json={**RETRIEVAL, **bad}).json()["code"] == 40001, bad


def test_chat_and_retrieval_settings_do_not_touch_each_other(client, admin_headers, conn, db_session_factory):
    client.put(f"{API}/retrieval", headers=admin_headers, json=RETRIEVAL)
    with db_session_factory() as db:
        retrieval_id = db.query(LlmProvider).one().id
    listed = client.get(f"{API}/providers", headers=admin_headers).json()["data"]
    assert listed["current"]["from_env"] and listed["others"] == []       # 检索那一行不出现在对话模型的列表里

    pid = client.post(f"{API}/providers", headers=admin_headers, json=BAILIAN).json()["data"]["id"]
    client.post(f"{API}/providers/{pid}/activate", headers=admin_headers)
    assert provider.current().id == pid and not provider.retrieval().from_env                     # 换对话模型不会把检索的配置停掉
    for method, path in (("post", f"/providers/{retrieval_id}/activate"), ("post", f"/providers/{retrieval_id}/test"),
                         ("delete", f"/providers/{retrieval_id}")):                               # 拿检索那一行的 id 当对话模型用：不存在
        assert client.request(method, API + path, headers=admin_headers).json()["code"] == 40401, path
    assert client.put(f"{API}/providers/{retrieval_id}/key", headers=admin_headers, json={"api_key": KEY}).json()["code"] == 40401

    client.delete(f"{API}/retrieval", headers=admin_headers)
    assert provider.retrieval().from_env and provider.current().id == pid                          # 反过来也一样
    with db_session_factory() as db:
        assert [(r.purpose, r.is_active) for r in db.query(LlmProvider).all()] == [("chat", True)]
        provider.reset()
        provider.load(db)                                                  # 重启后读回来的还是这两份
        assert provider.current().id == pid and provider.retrieval().from_env


class _FakeHttp:
    """按路径给回复：{"/embeddings": (状态码, 响应体), "/rerank": ...}；给异常就抛。"""

    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def post(self, url, json=None, headers=None, timeout=None):
        path = "/" + url.rsplit("/", 1)[1]
        self.calls.append((url, headers["Authorization"], json["model"], timeout))
        reply = self.replies[path]
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(reply[0], json=reply[1], request=httpx.Request("POST", url))


_VECTOR = (200, {"data": [{"index": 0, "embedding": [0.1] * 1024}]})
_RANKED = (200, {"results": [{"index": 0, "relevance_score": 0.9}, {"index": 1, "relevance_score": 0.1}]})


@pytest.mark.parametrize("replies, passed, says", [
    ({"/embeddings": _VECTOR, "/rerank": _RANKED}, True, "连上了：向量 1024 维，重排正常"),
    ({"/embeddings": (401, {}), "/rerank": _RANKED}, False, "密钥无效（401）"),
    ({"/embeddings": (400, {"message": "Model does not exist"}), "/rerank": _RANKED}, False, "向量模型被拒绝了（400），多半是模型名不对"),
    ({"/embeddings": _VECTOR, "/rerank": (400, {})}, False, "重排模型被拒绝了（400）"),
    ({"/embeddings": _VECTOR, "/rerank": (404, {})}, False, "重排的接口地址不对（404）"),
    ({"/embeddings": (503, {}), "/rerank": _RANKED}, False, "服务繁忙（503）"),
    ({"/embeddings": httpx.ConnectError("refused"), "/rerank": _RANKED}, False, "连不上（ConnectError）"),
    ({"/embeddings": (200, {"vectors": []}), "/rerank": _RANKED}, False, "向量接口返回的格式不对"),      # 接口不是这个格式的服务：挡在外面
    ({"/embeddings": _VECTOR, "/rerank": (200, {"data": []})}, False, "重排接口返回的格式不对"),
])
def test_retrieval_check_says_which_step_went_wrong(monkeypatch, replies, passed, says):
    http = _FakeHttp(replies)
    monkeypatch.setattr(registry, "http_client", lambda: http)
    r = Retrieval(False, "https://x.example.com/v1/", KEY, "embed-model", "rerank-model")
    ok, message, ms = provider_service.test_retrieval(r)
    assert ok is passed and says in message and (ms is not None) == passed
    assert http.calls[0] == ("https://x.example.com/v1/embeddings", f"Bearer {KEY}", "embed-model", provider_service.TEST_TIMEOUT)
    assert provider_service.test_retrieval(Retrieval(False, "https://x.example.com/v1", "", "e", "r")) == (False, "没有配置 API Key", None)


def test_switching_the_embedding_model_starts_the_vector_store_over(monkeypatch):
    """集合的维度在第一次写入时就定死了：换了向量模型只删记录不够，要整个集合删掉重建，新维度的向量才存得进去。"""
    import chromadb

    from app.retrieval import chroma_client, context_store

    memory = chromadb.EphemeralClient()
    monkeypatch.setattr(chroma_client, "_client", lambda: memory)
    monkeypatch.setattr(context_store, "_default_store", None)
    name = chroma_client.INTERVIEW_CTX
    chroma_client.drop_collection(name)                                    # 本来就没有：不抛
    old = chroma_client.get_collection(name)
    old.add(ids=["1:0"], embeddings=[[0.1, 0.2, 0.3]], documents=["旧模型算的切段"], metadatas=[{"session_id": 1}])
    with pytest.raises(Exception):                                         # noqa: B017 —— 维度不一样，直接存不进去
        old.add(ids=["2:0"], embeddings=[[0.1] * 5], documents=["新模型算的"], metadatas=[{"session_id": 2}])

    monkeypatch.setattr(context_store, "_default_store", object())
    context_store.drop_all()
    assert context_store._default_store is None                            # 手里那个集合对象作废，下次重新打开
    fresh = chroma_client.get_collection(name)
    assert fresh.count() == 0
    fresh.add(ids=["2:0"], embeddings=[[0.1] * 5], documents=["新模型算的"], metadatas=[{"session_id": 2}])
    assert fresh.count() == 1
    chroma_client.drop_collection(name)
