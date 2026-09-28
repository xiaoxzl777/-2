"""模拟面试（图 B）：接口走完整流程，检查点用内存版、面经检索用内存 Chroma + 假向量，模型全部打桩。"""
import json
import uuid
from datetime import datetime, timedelta

import chromadb
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.graphs.checkpoint import thread_config
from app.interview import policy, rubric
from app.interview.materials import build_materials
from app.interview.planner import _Topic, _verify
from app.llm.client import LLMError
from app.models import InterviewSession, InterviewTurn
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


def test_idle_interviews_are_abandoned_with_a_report(client, auth_headers, applied, fake_llm, env, db_session_factory):
    from app.services import interview_service

    script(fake_llm, evals=[evaluation(["先更新数据库再删缓存"], decision="next")])
    fake_llm.replies["_PlanOut"] = [PLAN, PLAN]
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


# ───────────── 领域层的纯函数 ─────────────


def test_evaluation_evidence_must_quote_the_answer():
    llm = FakeLLM({"_EvalOut": [evaluation(["我从没说过这句话"]), evaluation(["先更新数据库再删缓存"])]})
    ev, _ = rubric.evaluate(llm, job_title="后端", topic={"label": "缓存", "intent": "x"}, question=Q1, answer=A1)
    assert not ev["low_evidence"] and ev["scores"]["depth"] == 2
    assert "我从没说过这句话" in llm.calls["_EvalOut"][1][-1][1]                          # 重试时告诉它哪句找不到

    llm = FakeLLM({"_EvalOut": [evaluation(["编的"]), evaluation([], scores=(5, 5, 5))]})
    ev, _ = rubric.evaluate(llm, job_title="后端", topic={"label": "缓存", "intent": "x"}, question=Q1, answer=A1)
    assert ev["low_evidence"] and ev["scores"] == {"correctness": 3, "depth": 3, "clarity": 3} and ev["score"] == 60


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
        structure={"projects": [{"name": "订单系统", "char_start": 0, "char_end": 4}]}, masked_text="负责订单",
        findings=[{"id": 12, "title": "没写结果", "description": "d", "char_start": 0, "char_end": 4}],
        context=None, context_mode="none")
    assert [r["code"] for r in materials["requirements"]] == ["R4"]                     # 软素质不进面试
    topics = [_Topic(source=s, ref=r, label="话题" * 20, intent="i") for s, r in
              [("finding", "F12"), ("finding", "f12"), ("project", "R4"), ("requirement", "R4"), ("project", "P1")]]
    kept, rejected = _verify(topics, materials, 2)
    assert [t["ref"] for t in kept] == ["F12", "R4"] and rejected == 2 and len(kept[0]["label"]) == 20


def test_chunks_and_digit_masking():
    chunks = chunk_text("\n\n".join(["短段落"] * 3 + ["长" * 1200]), size=500, overlap=80)
    assert chunks[0].startswith("短段落\n短段落") and all(len(c) <= 500 for c in chunks) and len(chunks) == 4
    assert mask_new_numbers("影响行数为 0，从 800ms 降到 120ms", "", keep_digits=True) == ("影响行数为 0，从 【数值】ms 降到 【数值】ms", 2)
    assert mask_new_numbers("影响行数为 0", "")[1] == 1                                   # 具体建议仍然严格
