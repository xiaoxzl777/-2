"""模拟面试（图 B）：接口走完整流程，检查点用内存版、面经检索用内存 Chroma + 假向量，模型全部打桩。"""
import asyncio
import json
import uuid
from datetime import datetime, timedelta

import chromadb
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.graphs.checkpoint import thread_config
from app.interview import policy, rubric
from app.interview.materials import build_materials, describe_source
from app.interview.planner import _Topic, _verify, plan_interview
from app.llm.client import LLMError
from app.models import InterviewSession, InterviewTurn, MatchReport
from app.retrieval.context_store import ContextStore, chunk_text
from app.rewrite.advice import mask_new_numbers
from tests.conftest import FakeEmbedder, FakeLLM, apply as _apply

API = "/api/v1/interviews"

PLAN = json.dumps({"topics": [
    {"source": "project", "ref": "P1", "label": "订单系统 · 缓存", "intent": "深挖缓存改造是不是本人做的"},
    {"source": "requirement", "ref": "R9", "label": "不存在的要求", "intent": "x"},          # 编号不存在 → 丢掉
    {"source": "requirement", "ref": "P1", "label": "来源和编号对不上", "intent": "x"},       # 来源对不上 → 丢掉
    {"source": "requirement", "ref": "r4", "label": "消息队列", "intent": "确认是否了解 Kafka"},  # 小写也认
]}, ensure_ascii=False)
Q1, Q2, Q3 = "订单系统的缓存是怎么做的？", "你说先更新数据库再删缓存，删失败了怎么办？", "你用过 Kafka 吗？"
A1, A2 = "我是先更新数据库再删缓存的，热点商品提前预热。", "缓存设了过期时间兜底，最多旧一会儿。"


def evaluation(evidence, decision="followup", scores=(4, 2, 4), better="先更新数据库再删缓存，接口从 800ms 降到 120ms"):
    return json.dumps({"scores": dict(zip(("correctness", "depth", "clarity"), scores)), "evidence": evidence,
                       "good": "方向对", "bad": "没讲并发", "better_answer": better, "decision": decision},
                      ensure_ascii=False)


SUMMARY = json.dumps({"strengths": [{"title": "思路清楚", "detail": "缓存那题"}],
                      "weaknesses": [{"title": "消息队列不会", "detail": "跳过了"}],
                      "links": [{"ref": "R4", "text": "先补消息队列的基础"}, {"ref": "F999", "text": "编的"}]},
                     ensure_ascii=False)


def sse(response) -> list[tuple[str, dict]]:
    out = []
    for block in response.text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        out.append((fields["event"], json.loads(fields["data"])))
    return out


def names(events) -> list[str]:
    """把连续的 question 事件合成一个，方便断言事件顺序。"""
    out = []
    for name, _ in events:
        if not (name == "question" and out and out[-1] == "question"):
            out.append(name)
    return out


def question_text(events) -> str:
    return "".join(d["delta"] for n, d in events if n == "question")


@pytest.fixture
def env(client):
    """内存检查点 + 内存向量库。返回可变的字典，测试里可以把检查点换掉（模拟丢失）。"""
    from app.graphs.checkpoint import get_checkpointer
    from app.main import app
    from app.retrieval.context_store import get_context_store

    embedder = FakeEmbedder()
    collection = chromadb.EphemeralClient().create_collection(f"t_{uuid.uuid4().hex}", metadata={"hnsw:space": "cosine"},
                                                             embedding_function=None)
    state = {"saver": InMemorySaver(), "store": ContextStore(collection, embedder), "collection": collection}
    app.dependency_overrides[get_checkpointer] = lambda: state["saver"]
    app.dependency_overrides[get_context_store] = lambda: state["store"]
    return state


@pytest.fixture
def applied(client, auth_headers, resume_and_job, fake_llm, monkeypatch):
    """一次跑完的投递（规则诊断 + 词典匹配，不调模型）。返回生成投递的函数：passed=True 时把初筛线调低让它通过。"""
    from app.config import settings

    def make(passed=False) -> int:
        monkeypatch.setattr(settings, "SCREEN_THRESHOLD", 50.0 if passed else 60.0)   # 这份投递的匹配度约 57
        rid, jid = resume_and_job
        return _apply(client, auth_headers, rid, jid, match_mode="dict_only", diagnose_mode="rule_only")["data"]["id"]
    return make


def create(client, headers, apply_id, **extra):
    return client.post(API, headers=headers, json={"apply_id": apply_id, **extra}).json()


def script(fake_llm, *, evals, questions=(Q1, Q2, Q3)):
    fake_llm.replies["_PlanOut"] = [PLAN]
    fake_llm.replies["interview_ask"] = list(questions)
    fake_llm.replies["_EvalOut"] = list(evals)
    fake_llm.replies["_SummaryOut"] = [SUMMARY]


# ───────────── 完整流程 ─────────────


def test_practice_interview_end_to_end(client, auth_headers, applied, fake_llm, env, db_session_factory):
    script(fake_llm, evals=[evaluation(["先更新数据库再删缓存"]),
                            evaluation(["设了过期时间兜底"], decision="followup", scores=(4, 3, 4))])  # 已经追问过一次，不再追问
    created = create(client, auth_headers, applied(passed=False), company_name="示例科技")
    data = created["data"]
    assert (data["mode"], data["topic_count"], data["context_mode"], data["gate"]["passed"]) == ("practice", 2, "none", False)
    sid = data["id"]
    plan_prompt = fake_llm.calls["_PlanOut"][0][1][1]
    assert "P1 项目：订单系统" in plan_prompt and "R4 [必须]" in plan_prompt and "本科" not in plan_prompt  # 学历不进面试

    # 开始：第一个话题出现，题目流式出来（第一题带开场白），然后等回答
    started = sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
    assert names(started) == ["topic", "asking", "question", "asked"] and started[1][1] == {"topic_idx": 0, "depth": 0}
    assert started[0][1] == {"idx": 0, "label": "订单系统 · 缓存", "source": "project", "count": 2}
    assert question_text(started) == started[-1][1]["text"] == f"你好，我是示例科技的技术面试官，今天大概聊 2 个话题。\n{Q1}"
    view = client.get(f"{API}/{sid}", headers=auth_headers).json()["data"]
    assert [t["label"] for t in view["topics"]] == ["订单系统 · 缓存"] and view["waiting"]   # 没问到的话题不给

    # 答第一题：练习模式先给点评，模型要追问 → 同一话题的追问
    first = sse(client.post(f"{API}/{sid}/answer", headers=auth_headers, json={"text": A1}))
    assert names(first) == ["evaluation", "asking", "question", "asked"] and first[1][1]["depth"] == 1
    ev = first[0][1]
    assert ev["score"] == 67 and ev["evidence"][0]["quote"] == "先更新数据库再删缓存" and not ev["low_evidence"]
    assert ev["better_answer"] == "先更新数据库再删缓存，接口从 【数值】ms 降到 【数值】ms"   # 回答里没有的数字不能替他编
    assert first[-1][1]["depth"] == 1 and first[-1][1]["text"] == Q2
    ask_prompt = fake_llm.calls["interview_ask"][1][1][1]
    assert A1 in ask_prompt and "没讲并发" in ask_prompt                                     # 追问带着上一答和不足

    # 答追问：模型还想追问，但每个话题最多追问 1 次 → 换到下一个话题
    second = sse(client.post(f"{API}/{sid}/answer", headers=auth_headers, json={"text": A2}))
    assert names(second) == ["evaluation", "topic", "asking", "question", "asked"]
    assert second[1][1]["label"] == "消息队列" and second[-1][1]["depth"] == 0

    # 跳过最后一题：不调模型评分，记 0 分；话题用完 → 出报告
    evals_before = len(fake_llm.calls["_EvalOut"])
    last = sse(client.post(f"{API}/{sid}/answer", headers=auth_headers, json={"skip": True}))
    assert names(last) == ["finished"]                                                     # 跳过的题不给点评
    assert len(fake_llm.calls["_EvalOut"]) == evals_before
    assert last[-1][1] == {"report_ready": True, "verdict": "practice", "overall": 35}

    report = client.get(f"{API}/{sid}/report", headers=auth_headers).json()["data"]
    r = report["report"]
    assert [(t["label"], t["score"]) for t in r["topics"]] == [("订单系统 · 缓存", 70), ("消息队列", 0)]
    assert (r["overall"], r["verdict"], r["answered"], r["early"], r["summary_ok"]) == (35, "practice", 3, False, True)
    assert r["strengths"][0]["title"] == "思路清楚"
    assert r["links"] == [{"kind": "requirement", "ref_id": 4, "topic_idx": 1, "label": "熟悉 Kafka", "text": "先补消息队列的基础"}]
    assert [(t["depth"], t["skipped"], t["evaluation"]["score"]) for t in report["turns"]] == [(0, False, 67), (1, False, 73), (0, True, 0)]

    with db_session_factory() as db:
        session = db.get(InterviewSession, sid)
        assert session.status == "completed" and session.finished_at and session.cost > 0
    assert env["saver"].get_tuple(thread_config(sid)) is None                                 # 检查点线程已删
    assert client.post(f"{API}/{sid}/start", headers=auth_headers).json()["code"] == 40901


def test_interview_follows_the_job_direction(client, auth_headers, applied, resume_and_job, fake_llm, env,
                                              db_session_factory):
    """岗位是运营方向：定话题、出题按运营岗面试来，开场白、接口返回的方向也跟着变。"""
    from app.models import Job

    with db_session_factory() as db:
        db.get(Job, resume_and_job[1]).domain = "ops"
        db.commit()
    script(fake_llm, evals=[evaluation(["先更新数据库再删缓存"])])
    sid = create(client, auth_headers, applied(passed=False))["data"]["id"]
    assert "运营岗面试" in fake_llm.calls["_PlanOut"][0][0][1]
    started = sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
    assert started[-1][1]["text"].startswith("你好，我是这次的运营面试官")
    assert "运营面试官" in fake_llm.calls["interview_ask"][0][0][1]
    assert client.get(f"{API}/{sid}", headers=auth_headers).json()["data"]["domain"] == "ops"


def test_normal_mode_hides_evaluation_until_the_end(client, auth_headers, applied, fake_llm, env):
    script(fake_llm, evals=[evaluation(["先更新数据库再删缓存"], decision="next")])
    sid = create(client, auth_headers, applied(passed=True))["data"]["id"]
    assert client.get(f"{API}/{sid}", headers=auth_headers).json()["data"]["mode"] == "normal"
    sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
    answered = sse(client.post(f"{API}/{sid}/answer", headers=auth_headers, json={"text": A1}))
    assert "evaluation" not in names(answered) and names(answered) == ["topic", "asking", "question", "asked"]
    assert client.get(f"{API}/{sid}", headers=auth_headers).json()["data"]["turns"][0]["evaluation"] is None

    # 提前结束：只按评完分的题出报告（第二题出了还没答，不算）
    finished = client.post(f"{API}/{sid}/finish", headers=auth_headers).json()["data"]
    assert finished["status"] == "completed" and finished["report"]["early"]
    assert [t["score"] for t in finished["report"]["topics"]] == [67, None]
    assert finished["report"]["verdict"] == "incomplete"                               # 没聊完就结束：不下结论
    assert finished["turns"][0]["evaluation"]["score"] == 67
    assert client.post(f"{API}/{sid}/finish", headers=auth_headers).json()["code"] == 40901
    assert env["saver"].get_tuple(thread_config(sid)) is None


def test_practice_can_be_chosen_even_after_passing(client, auth_headers, applied, fake_llm, env):
    script(fake_llm, evals=[])
    assert create(client, auth_headers, applied(passed=True), practice=True)["data"]["mode"] == "practice"


# ───────────── 刷新、重复提交、失败后继续、检查点丢失 ─────────────


def test_restart_resends_the_pending_question_and_answers_are_checked(client, auth_headers, applied, fake_llm, env):
    script(fake_llm, evals=[evaluation(["先更新数据库再删缓存"], decision="next")])
    sid = create(client, auth_headers, applied())["data"]["id"]
    answer = lambda **body: client.post(f"{API}/{sid}/answer", headers=auth_headers, json=body)     # noqa: E731
    assert answer(text=A1).json()["code"] == 40901                                    # 还没开始

    asked = sse(client.post(f"{API}/{sid}/start", headers=auth_headers))[-1]
    again = sse(client.post(f"{API}/{sid}/start", headers=auth_headers))                # 页面刷新后再点开始
    assert again == [asked] and len(fake_llm.calls["interview_ask"]) == 1             # 同一道题，不会再出一题

    assert answer(text="   ").json()["code"] == 40001
    assert "3000" in answer(text="字" * 3001).json()["message"]
    assert names(sse(answer(text=A1))) == ["evaluation", "topic", "asking", "question", "asked"]
    assert client.get(f"{API}/{sid}", headers=auth_headers).json()["data"]["turns"][0]["answer"] == A1


def test_leaving_while_the_report_is_written_still_cleans_up(client, auth_headers, applied, fake_llm, env, db_session_factory):
    """等报告时关了页面：生成器在发出 finished 的那一刻被关掉，检查点线程和面经切段照样要删。"""
    from app.services import interview_service

    script(fake_llm, evals=[evaluation(["先更新数据库再删缓存"]), evaluation(["设了过期时间兜底"])])
    sid = create(client, auth_headers, applied(), extra_context="面经：" + "先问缓存怎么保证一致，再问消息队列。" * 220)["data"]["id"]
    assert len(env["collection"].get(where={"session_id": sid})["ids"]) > 1          # 面经超过 3000 字，切段进了向量库
    sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
    sse(client.post(f"{API}/{sid}/answer", headers=auth_headers, json={"text": A1}))
    sse(client.post(f"{API}/{sid}/answer", headers=auth_headers, json={"text": A2}))

    with db_session_factory() as db:                                                 # 最后一题：直接驱动生成器，好在半路关掉
        answer = interview_service.submit_answer(db, db.get(InterviewSession, sid), "", True)
    events = interview_service.advance(sid, answer, llm=fake_llm, store=env["store"], checkpointer=env["saver"],
                                       session_factory=db_session_factory)
    assert next(events)[0] == "finished"
    events.close()                                                                   # 页面关了

    with db_session_factory() as db:
        assert db.get(InterviewSession, sid).status == "completed"
    assert env["saver"].get_tuple(thread_config(sid)) is None
    assert env["collection"].get(where={"session_id": sid})["ids"] == []


def test_a_drop_right_after_the_question_is_saved_neither_repeats_it_nor_loses_the_answer(client, auth_headers, applied,
                                                                                         fake_llm, env, db_session_factory):
    """题目刚落库、图还没走到"等回答"时连接断了：用户照样看到了题、提交了回答。回答要算数，同一道题不能再存一遍。"""
    from app.services import interview_service

    script(fake_llm, evals=[evaluation(["先更新数据库再删缓存"])])
    sid = create(client, auth_headers, applied())["data"]["id"]
    kwargs = dict(llm=fake_llm, store=env["store"], checkpointer=env["saver"], session_factory=db_session_factory)
    with db_session_factory() as db:
        interview_service.begin(db, db.get(InterviewSession, sid))
    events = interview_service.advance(sid, None, **kwargs)
    for name, _ in events:
        if name == "asked":
            events.close()                                                           # 就断在这里
            break

    with db_session_factory() as db:
        answer = interview_service.submit_answer(db, db.get(InterviewSession, sid), A1, False)
    after = list(interview_service.advance(sid, answer, **kwargs))
    assert "error" not in names(after) and "evaluation" in names(after)             # 回答被评了分
    with db_session_factory() as db:
        turns = db.query(InterviewTurn).filter_by(session_id=sid).order_by(InterviewTurn.turn_no).all()
        assert turns[0].question.endswith(Q1) and turns[0].answer == A1 and turns[0].evaluation is not None
        assert sum(t.question.endswith(Q1) for t in turns) == 1                      # 同一道题只存了一遍
    assert len(fake_llm.calls["interview_ask"]) == len(turns)                        # 没有多调一次模型出题


def test_interviews_work_when_the_vector_store_cannot_open(client, auth_headers, applied, fake_llm, env, monkeypatch):
    """向量库打不开：依赖给 None，不抛异常。没贴面经的照常面；贴了长面经的退回整段截取、不检索。"""
    from app.main import app
    from app.retrieval import chroma_client, context_store
    from app.retrieval.context_store import get_context_store

    def broken(_name):
        raise RuntimeError("chroma 数据目录损坏")

    monkeypatch.setattr(chroma_client, "get_collection", broken)
    monkeypatch.setattr(context_store, "_default_store", None)
    assert get_context_store() is None and get_context_store() is None                 # 不抛；失败不记住，下次再试
    app.dependency_overrides[get_context_store] = get_context_store                    # 用真的依赖（打不开的那个）

    script(fake_llm, evals=[])
    plain = create(client, auth_headers, applied())
    assert plain["code"] == 0 and plain["data"]["context_mode"] == "none"
    assert names(sse(client.post(f"{API}/{plain['data']['id']}/start", headers=auth_headers)))[-1] == "asked"
    fake_llm.replies["_PlanOut"] = [PLAN]
    long = create(client, auth_headers, applied(), extra_context="面经：" + "先问缓存怎么保证一致。" * 400)
    assert long["code"] == 0 and long["data"]["context_mode"] == "full"


def test_a_request_waits_for_the_previous_step_of_the_same_interview(client, auth_headers, applied, fake_llm, env,
                                                                   db_session_factory, monkeypatch):
    """页面刷新：上一步的流被掐断、还在收尾，刷新后的请求就到了。先等它收完再接着走；等太久才报「上一步还在进行」。"""
    import threading

    from app.services import interview_service

    script(fake_llm, evals=[])
    sid = create(client, auth_headers, applied())["data"]["id"]
    kwargs = dict(llm=fake_llm, store=env["store"], checkpointer=env["saver"], session_factory=db_session_factory)

    interview_service._running.add(sid)                                              # 上一步还占着
    threading.Timer(0.3, interview_service._running.discard, [sid]).start()          # 0.3 秒后收尾完
    assert names(list(interview_service.advance(sid, None, **kwargs)))[-1] == "asked"

    monkeypatch.setattr(interview_service, "WAIT_PREVIOUS_SECONDS", 0.3)             # 一直不收尾：等一会儿就放弃
    interview_service._running.add(sid)
    try:
        assert list(interview_service.advance(sid, None, **kwargs)) == [("error", {"code": 40901, "message": "上一步还在进行，请稍等"})]
    finally:
        interview_service._running.discard(sid)


def test_a_down_model_service_is_named_when_starting_and_mid_interview(client, auth_headers, applied, fake_llm, env):
    down = LLMError("调用失败", unavailable="余额不足（402）")
    fake_llm.replies["_PlanOut"] = [down]
    r = create(client, auth_headers, applied())
    assert (r["code"], r["message"]) == (50002, "模型服务暂时不可用，请稍后再试")

    script(fake_llm, evals=[down])
    sid = create(client, auth_headers, applied())["data"]["id"]
    sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
    failed = sse(client.post(f"{API}/{sid}/answer", headers=auth_headers, json={"text": A1}))
    assert failed[-1] == ("error", {"code": 50002, "message": "模型服务暂时不可用，恢复后点重试，会从这一题接着面"})


def test_a_failed_step_can_be_continued(client, auth_headers, applied, fake_llm, env, db_session_factory):
    script(fake_llm, evals=[LLMError("上游超时")])
    sid = create(client, auth_headers, applied())["data"]["id"]
    sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
    failed = sse(client.post(f"{API}/{sid}/answer", headers=auth_headers, json={"text": A1}))
    assert failed[-1] == ("error", {"code": 50002, "message": "面试官这边出了点问题，请重试"})
    with db_session_factory() as db:
        turn = db.query(InterviewTurn).filter_by(session_id=sid).one()
        assert turn.answer == A1 and turn.evaluation is None                       # 回答先落了库，没丢
    again = client.post(f"{API}/{sid}/answer", headers=auth_headers, json={"text": "再答一次"}).json()
    assert again["code"] == 40901 and "答过了" in again["message"]                  # 同一题只能答一次

    fake_llm.replies["_EvalOut"] = [evaluation(["先更新数据库再删缓存"], decision="next")]
    resumed = sse(client.post(f"{API}/{sid}/start", headers=auth_headers))           # 从评分那一步接着跑
    assert names(resumed) == ["evaluation", "topic", "asking", "question", "asked"]


def test_lost_checkpoint_is_rebuilt_from_the_database(client, auth_headers, applied, fake_llm, env):
    script(fake_llm, evals=[evaluation(["先更新数据库再删缓存"])])
    sid = create(client, auth_headers, applied())["data"]["id"]
    sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
    env["saver"] = InMemorySaver()                                                   # 检查点文件没了
    rebuilt = sse(client.post(f"{API}/{sid}/answer", headers=auth_headers, json={"text": A1}))
    assert names(rebuilt) == ["evaluation", "asking", "question", "asked"] and rebuilt[-1][1]["depth"] == 1
    assert A1 in fake_llm.calls["interview_ask"][1][1][1]                               # 重建的状态里带着这个话题的问答


def test_a_checkpoint_lost_before_the_first_question_or_after_scoring_is_rebuilt_too(client, auth_headers, applied,
                                                                                    fake_llm, env):
    """检查点丢在另外两个时刻：还没出过题（从选话题接着走）；一题评完分、下一题没出来（从「决定下一步」接着走，不重新评分）。"""
    script(fake_llm, evals=[evaluation(["先更新数据库再删缓存"], decision="next")], questions=[Q1, LLMError("上游超时"), Q3])
    sid = create(client, auth_headers, applied())["data"]["id"]
    env["saver"] = InMemorySaver()
    first = sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
    assert names(first) == ["topic", "asking", "question", "asked"] and first[-1][1]["text"].endswith(Q1)

    failed = sse(client.post(f"{API}/{sid}/answer", headers=auth_headers, json={"text": A1}))   # 评完分，下一题没出来
    assert names(failed)[0] == "evaluation" and failed[-1][0] == "error"
    env["saver"] = InMemorySaver()
    resumed = sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
    assert names(resumed) == ["topic", "asking", "question", "asked"]
    assert resumed[0][1]["label"] == "消息队列" and resumed[-1][1]["text"] == Q3           # 换到下一个话题，不带开场白
    assert len(fake_llm.calls["_EvalOut"]) == 1                                        # 评过的那题不重新评


def test_a_first_question_that_did_not_come_out_can_be_asked_again(client, auth_headers, applied, fake_llm, env,
                                                                  db_session_factory):
    """第一题没出来（模型只回了空白）：什么都不存；这时提交回答会被拒绝；再点开始，重新出这一题。"""
    script(fake_llm, evals=[], questions=["   ", Q1])
    sid = create(client, auth_headers, applied())["data"]["id"]
    failed = sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
    assert failed[-1] == ("error", {"code": 50002, "message": "面试官这边出了点问题，请重试"})
    with db_session_factory() as db:
        assert db.query(InterviewTurn).filter_by(session_id=sid).count() == 0
    refused = client.post(f"{API}/{sid}/answer", headers=auth_headers, json={"text": A1}).json()
    assert (refused["code"], refused["message"]) == (40901, "还没有出题")

    again = sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
    assert names(again)[-1] == "asked" and again[-1][1]["text"].endswith(Q1)


def test_start_picks_up_an_answer_that_was_saved_but_never_processed(client, auth_headers, applied, fake_llm, env,
                                                                    db_session_factory):
    """回答落了库、图还没来得及往下走进程就没了：再点开始，带着库里的回答接着评分，不用用户重答。"""
    from app.services import interview_service

    script(fake_llm, evals=[evaluation(["先更新数据库再删缓存"], decision="next")])
    sid = create(client, auth_headers, applied())["data"]["id"]
    sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
    with db_session_factory() as db:
        interview_service.submit_answer(db, db.get(InterviewSession, sid), A1, False)   # 只存了回答，没往下走

    resumed = sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
    assert names(resumed) == ["evaluation", "topic", "asking", "question", "asked"]
    assert A1 in fake_llm.calls["_EvalOut"][0][-1][1]                                   # 评的是库里那句回答


def test_a_refresh_after_a_drop_shows_the_same_question_again(client, auth_headers, applied, fake_llm, env,
                                                             db_session_factory):
    """题目刚落库连接就断了，用户刷新页面（不是提交回答）：把库里那道题再发一次，不再调模型出一题、不再存一遍。"""
    from app.services import interview_service

    script(fake_llm, evals=[])
    sid = create(client, auth_headers, applied())["data"]["id"]
    kwargs = dict(llm=fake_llm, store=env["store"], checkpointer=env["saver"], session_factory=db_session_factory)
    with db_session_factory() as db:
        interview_service.begin(db, db.get(InterviewSession, sid))
    events = interview_service.advance(sid, None, **kwargs)
    asked = next(data for name, data in events if name == "asked")
    events.close()                                                                   # 就断在这里

    again = list(interview_service.advance(sid, None, **kwargs))
    assert again[-1] == ("asked", asked) and len(fake_llm.calls["interview_ask"]) == 1
    with db_session_factory() as db:
        assert db.query(InterviewTurn).filter_by(session_id=sid).count() == 1


def test_finishing_waits_its_turn_and_survives_a_failed_cleanup(client, auth_headers, applied, fake_llm, env, monkeypatch):
    """提前结束：上一步还在跑时先拒绝（不然两边同时写这场面试）；清理检查点出错不影响结果，报告已经落库。"""
    from app.services import interview_service

    script(fake_llm, evals=[])
    sid = create(client, auth_headers, applied())["data"]["id"]
    sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
    interview_service._running.add(sid)
    try:
        busy = client.post(f"{API}/{sid}/finish", headers=auth_headers).json()
    finally:
        interview_service._running.discard(sid)
    assert (busy["code"], busy["message"]) == (40901, "上一步还在进行，请稍等")

    def broken(_thread_id):
        raise RuntimeError("检查点文件被占用")

    monkeypatch.setattr(env["saver"], "delete_thread", broken)
    done = client.post(f"{API}/{sid}/finish", headers=auth_headers).json()
    assert done["code"] == 0 and done["data"]["status"] == "completed"
    assert client.get(f"{API}/{sid}/report", headers=auth_headers).json()["data"]["report"]["early"]


def test_the_report_is_still_written_when_the_summary_fails(client, auth_headers, applied, fake_llm, env):
    """报告里的文字总结调不通、或者输出不合格：分数和逐题回顾照常给，只是没有总结（summary_ok 为假）。"""
    for bad in (LLMError("上游超时"), "这不是 JSON"):
        script(fake_llm, evals=[evaluation(["先更新数据库再删缓存"], decision="next")])
        fake_llm.replies["_SummaryOut"] = [bad]
        sid = create(client, auth_headers, applied())["data"]["id"]
        sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
        sse(client.post(f"{API}/{sid}/answer", headers=auth_headers, json={"text": A1}))
        finished = client.post(f"{API}/{sid}/finish", headers=auth_headers).json()["data"]
        report = finished["report"]
        assert finished["status"] == "completed" and not report["summary_ok"]
        assert (report["strengths"], report["weaknesses"]) == ([], [])
        assert [t["score"] for t in report["topics"]] == [67, None] and finished["turns"][0]["evaluation"]["score"] == 67


# ───────────── 面经 ─────────────


def test_short_context_goes_in_whole_and_long_context_is_retrieved(client, auth_headers, applied, fake_llm, env):
    script(fake_llm, evals=[])
    apply_id = applied()
    short = create(client, auth_headers, apply_id, extra_context="一面问了缓存一致性和消息队列。")["data"]
    assert short["context_mode"] == "full"
    sse(client.post(f"{API}/{short['id']}/start", headers=auth_headers))
    assert "一面问了缓存一致性" in fake_llm.calls["interview_ask"][-1][1][1]

    script(fake_llm, evals=[])
    paragraphs = [f"第 {i} 轮：面试官问了{'Redis 缓存一致性' if i == 7 else '项目背景'}，" + "细节" * 120 for i in range(12)]
    long = create(client, auth_headers, apply_id, extra_context="\n\n".join(paragraphs))["data"]
    assert long["context_mode"] == "retrieval"
    assert len(env["collection"].get(where={"session_id": long["id"]})["ids"]) > 1
    sse(client.post(f"{API}/{long['id']}/start", headers=auth_headers))
    prompt = fake_llm.calls["interview_ask"][-1][1][1]
    assert "【参考：这家公司的面经 / 介绍】" in prompt and prompt.count("第 ") <= 3 * 2      # 只带检索到的几段
    client.post(f"{API}/{long['id']}/finish", headers=auth_headers)
    assert env["collection"].get(where={"session_id": long["id"]})["ids"] == []        # 结束就删


def test_questions_still_come_when_retrieval_fails(client, auth_headers, applied, fake_llm, env, monkeypatch):
    """面经只是参考：重排挂了按召回顺序带上；连向量也算不出来就不带面经，照样出题。"""
    def down(*args, **kwargs):
        raise LLMError("向量服务超时")

    script(fake_llm, evals=[evaluation(["先更新数据库再删缓存"], decision="next")])
    paragraphs = [f"第 {i} 轮：面试官问了{'Redis 缓存一致性' if i == 7 else '项目背景'}，" + "细节" * 120 for i in range(12)]
    sid = create(client, auth_headers, applied(), extra_context="\n\n".join(paragraphs))["data"]["id"]
    embedder = env["store"]._embedder

    monkeypatch.setattr(embedder, "rerank", down)
    assert names(sse(client.post(f"{API}/{sid}/start", headers=auth_headers)))[-1] == "asked"
    assert "【参考：这家公司的面经 / 介绍】" in fake_llm.calls["interview_ask"][-1][1][1]

    monkeypatch.setattr(embedder, "embed", down)
    answered = sse(client.post(f"{API}/{sid}/answer", headers=auth_headers, json={"text": A1}))
    assert names(answered)[-1] == "asked" and "【参考：这家公司的面经 / 介绍】" not in fake_llm.calls["interview_ask"][-1][1][1]


# ───────────── 拒绝、失败、清理 ─────────────


def test_rejections(client, auth_headers, applied, fake_llm, env, db_session_factory):
    apply_id = applied()
    fake_llm.replies["_PlanOut"] = ['{"topics": []}', '{"topics": [{"source": "project", "ref": "P7", "label": "x", "intent": "x"}]}']
    failed = create(client, auth_headers, apply_id)
    assert failed["code"] == 50002
    with db_session_factory() as db:
        assert db.query(InterviewSession).count() == 0                                 # 定不下话题就什么都不留

    assert create(client, auth_headers, 9999)["code"] == 40401
    script(fake_llm, evals=[])
    sid = create(client, auth_headers, apply_id)["data"]["id"]
    assert client.get(f"{API}/{sid}/report", headers=auth_headers).json()["code"] == 40901
    other = client.post("/api/v1/auth/register", json={"username": "someone_else", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['data']['access_token']}"}
    assert client.get(f"{API}/{sid}", headers=other_headers).json()["code"] == 40401
    assert client.post(f"{API}/{sid}/start", headers=other_headers).json()["code"] == 40401
    assert create(client, other_headers, apply_id)["code"] == 40401

    with db_session_factory() as db:                                                   # 初筛还没跑完的投递：不能面
        done = db.get(MatchReport, apply_id)
        running = MatchReport(resume_id=done.resume_id, job_id=done.job_id, status="running", mode="hybrid")
        db.add(running)
        db.commit()
        running_id = running.id
    early = create(client, auth_headers, running_id)
    assert (early["code"], early["message"]) == (40901, "初筛还没完成，完成后才能面试")


def test_idle_interviews_are_abandoned_with_a_report(client, auth_headers, applied, fake_llm, env, db_session_factory):
    from app.services import interview_service

    script(fake_llm, evals=[evaluation(["先更新数据库再删缓存"], decision="next")])
    fake_llm.replies["_PlanOut"] = [PLAN] * 4              # 建两场；PLAN 里能用的话题不够，每场都会重试一次
    apply_id = applied()
    sid = create(client, auth_headers, apply_id)["data"]["id"]
    sse(client.post(f"{API}/{sid}/start", headers=auth_headers))
    sse(client.post(f"{API}/{sid}/answer", headers=auth_headers, json={"text": A1}))
    fresh = create(client, auth_headers, apply_id)["data"]["id"]                         # 刚创建的不动
    with db_session_factory() as db:
        db.get(InterviewSession, sid).last_active_at = datetime.now() - timedelta(hours=30)
        db.commit()
    assert interview_service.cleanup_idle(db_session_factory, env["saver"]) == 1
    with db_session_factory() as db:
        session = db.get(InterviewSession, sid)
        assert session.status == "abandoned" and session.report["topics"][0]["score"] == 67
        assert not session.report["summary_ok"] and db.get(InterviewSession, fresh).status == "planned"


def test_idle_sweep_keeps_running(monkeypatch):
    """服务开着时定时收尾；某一轮出错（比如库一时连不上）不能让循环停掉"""
    from app import main

    calls = []

    def sweep():
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("库连不上")
        return 0

    monkeypatch.setattr(main, "sweep_idle_interviews", sweep)

    async def run():
        task = asyncio.create_task(main.sweep_forever(0.01))
        await asyncio.sleep(0.2)
        task.cancel()

    asyncio.run(run())
    assert len(calls) >= 3


# ───────────── 领域层的纯函数 ─────────────


def test_evaluation_evidence_must_quote_the_answer():
    llm = FakeLLM({"_EvalOut": [evaluation(["我从没说过这句话"]), evaluation(["先更新数据库再删缓存"])]})
    ev, _ = rubric.evaluate(llm, job_title="后端", topic={"label": "缓存", "intent": "x"}, question=Q1, answer=A1)
    assert not ev["low_evidence"] and ev["scores"]["depth"] == 2
    assert "我从没说过这句话" in llm.calls["_EvalOut"][1][-1][1]                          # 重试时告诉它哪句找不到

    llm = FakeLLM({"_EvalOut": [evaluation(["编的"]), evaluation([], scores=(5, 5, 5))]})
    ev, _ = rubric.evaluate(llm, job_title="后端", topic={"label": "缓存", "intent": "x"}, question=Q1, answer=A1)
    assert ev["low_evidence"] and ev["scores"] == {"correctness": 3, "depth": 3, "clarity": 3} and ev["score"] == 60

    llm = FakeLLM({"_EvalOut": ["我觉得答得不错", evaluation(["先更新数据库再删缓存"])]})   # 第一次不是 JSON：带着报错再要一次
    ev, _ = rubric.evaluate(llm, job_title="后端", topic={"label": "缓存", "intent": "x"}, question=Q1, answer=A1)
    assert ev["scores"]["depth"] == 2 and len(llm.calls["_EvalOut"]) == 2
    with pytest.raises(ValueError, match="两次都不合格"):                              # 两次都不是：这一步失败，用户点重试
        rubric.evaluate(FakeLLM({"_EvalOut": ["不是 JSON", "还不是"]}), job_title="后端", topic={"label": "缓存", "intent": "x"},
                        question=Q1, answer=A1)


def test_scores_and_policy():
    plan = [{"idx": 0}, {"idx": 1}, {"idx": 2}]
    history = [{"topic_idx": 0, "evaluation": {"score": 80}},
               {"topic_idx": 0, "evaluation": {"score": 40, "low_evidence": True}},       # 权重减半
               {"topic_idx": 1, "evaluation": {"score": 0, "skipped": True}}]
    scores = rubric.topic_scores(plan, history)
    assert scores == [67, 0, None] and rubric.overall_score(scores) == 34
    assert rubric.verdict("normal", 60, 60) == "pass" and rubric.verdict("normal", 59, 60) == "fail"
    assert rubric.verdict("practice", 99, 60) == "practice" and rubric.verdict("normal", 99, 60, complete=False) == "incomplete"

    follow = {"decision": "followup"}
    assert policy.decide(follow, 0, 1, 0.1, 0.3) == "followup"
    assert policy.decide(follow, 1, 1, 0.1, 0.3) == "next"                              # 追问次数用完
    assert policy.decide({"decision": "followup", "skipped": True}, 0, 1, 0.1, 0.3) == "next"
    assert policy.decide(follow, 0, 1, 0.3, 0.3) == "finish"                            # 钱花到上限


def test_plan_topics_must_point_at_real_materials():
    materials = build_materials(
        job_title="后端", company=None,
        requirements=[{"id": 4, "req_type": "hard", "category": "skill", "content": "熟悉 Kafka"},
                      {"id": 5, "req_type": "soft", "category": "other", "content": "沟通好"}],
        match_items=[{"requirement_id": 4, "status": "miss", "reason": "没提到"}],
        structure={"projects": [{"name": "订单系统", "char_start": 0, "char_end": 4},
                                {"name": "原文里定位不到的项目", "char_start": None, "char_end": None}]}, masked_text="负责订单",
        findings=[{"id": 12, "title": "没写结果", "description": "d", "char_start": 0, "char_end": 4}],
        context=None, context_mode="none")
    assert [r["code"] for r in materials["requirements"]] == ["R4"]                     # 软素质不进面试
    assert [e["name"] for e in materials["experiences"]] == ["订单系统"]                 # 定位不到原文的经历没法问
    topics = [_Topic(source=s, ref=r, label="话题" * 20, intent="i") for s, r in
              [("finding", "F12"), ("finding", "f12"), ("project", "R4"), ("requirement", "R4"), ("project", "P1")]]
    kept, rejected = _verify(topics, materials, 2)
    assert [t["ref"] for t in kept] == ["F12", "R4"] and rejected == 2 and len(kept[0]["label"]) == 20
    # 话题指向简历问题时，给面试官看的是原文那一句和问题本身
    assert describe_source(materials, kept[0]) == "简历原文：「负责订单」\n初筛发现的问题：没写结果——d"


def test_plan_retries_when_topics_fall_short():
    materials = build_materials(
        job_title="后端", company=None,
        requirements=[{"id": 4, "req_type": "hard", "category": "skill", "content": "熟悉 Kafka"}],
        match_items=[{"requirement_id": 4, "status": "miss", "reason": "没提到"}],
        structure={"projects": [{"name": "订单系统", "char_start": 0, "char_end": 4}]}, masked_text="负责订单",
        findings=[{"id": 12, "title": "没写结果", "description": "d", "char_start": 0, "char_end": 4}],
        context=None, context_mode="none")                                              # 可问的一共 3 条
    source = {"P": "project", "R": "requirement", "F": "finding"}

    def plan(*refs):
        return json.dumps({"topics": [{"source": source[r[0]], "ref": r, "label": r, "intent": "i"} for r in refs]})

    llm = FakeLLM({"_PlanOut": [plan("P1", "R9", "F12"), plan("P1", "R4", "F12")]})       # R9 不存在 → 只剩 2 个，重试
    out = plan_interview(materials, 3, llm)
    assert [t["ref"] for t in out.topics] == ["P1", "R4", "F12"] and out.rejected == 0 and out.error is None
    assert "能用的只有 2 个，另外 1 个的 ref 在材料里找不到" in llm.calls["_PlanOut"][1][-1][1]

    llm = FakeLLM({"_PlanOut": [plan("P1", "F12"), plan("R4")]})                         # 重试反而更少：用第一次的
    assert [t["ref"] for t in plan_interview(materials, 3, llm).topics] == ["P1", "F12"]

    llm = FakeLLM({"_PlanOut": [plan("P1", "R4", "F12")]})                               # 材料只够 3 个，要 5 个也不重试
    assert len(plan_interview(materials, 5, llm).topics) == 3 and len(llm.calls["_PlanOut"]) == 1

    llm = FakeLLM({"_PlanOut": [plan("R9"), "不是 JSON"]})                                # 两次都没有能用的
    out = plan_interview(materials, 3, llm)
    assert out.topics == [] and out.error


def test_chunks_and_digit_masking():
    chunks = chunk_text("\n\n".join(["短段落"] * 3 + ["长" * 1200]), size=500, overlap=80)
    assert chunks[0].startswith("短段落\n短段落") and all(len(c) <= 500 for c in chunks) and len(chunks) == 4
    assert mask_new_numbers("影响行数为 0，从 800ms 降到 120ms", "", keep_digits=True) == ("影响行数为 0，从 【数值】ms 降到 【数值】ms", 2)
    assert mask_new_numbers("影响行数为 0", "")[1] == 1                                   # 具体建议仍然严格
