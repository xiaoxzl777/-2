"""具体建议：拼 prompt（领域函数）、数字复检，以及两个流式接口的生成、存库、复用与失败。"""
import json

from app.llm.client import LLMError
from app.models import Finding, MatchReport
from app.rewrite.advice import PLACEHOLDER, finding_prompt, fix_numbers, gap_prompt
from tests.conftest import apply, fulltext_reply

# ───────────── 领域函数 ─────────────

TEXT = ("张三\n电话：13812345678\n项目经历\n订单系统 后端开发 2024.03-2024.08\n"
        "1. 负责订单模块的开发，完成下单与退款流程。\n2. 使用 Redis 缓存热门商品，响应从 800ms 降到 120ms。\n"
        "专业技能\n熟悉 Java、Docker")


def _span(s: str) -> dict:
    return {"char_start": TEXT.index(s), "char_end": TEXT.index(s) + len(s)}


H1, H2 = "1. 负责订单模块的开发，完成下单与退款流程。", "2. 使用 Redis 缓存热门商品，响应从 800ms 降到 120ms。"
ENTRY = "订单系统 后端开发 2024.03-2024.08\n" + H1 + "\n" + H2
STRUCTURE = {"basics": {"name": "张三"},
             "projects": [{"name": "订单系统", "role": "后端开发", **_span(ENTRY), "highlights": [_span(H1), _span(H2)]}]}
MASKED = TEXT.replace("张三", "某某").replace("13812345678", "XXXXXXXXXXX")


def _user(prompt) -> str:
    return prompt.messages[1][1]


def test_finding_prompt_sends_the_sentence_and_its_entry_masked():
    finding = {"unit_id": "projects[0].highlights[0]", **_span("负责订单模块的开发"), "title": "只有做了什么，没有结果",
               "description": "没有说明带来了什么结果。", "evidence_quote": "负责订单模块的开发"}
    p = finding_prompt(finding, STRUCTURE, TEXT, MASKED, "后端开发实习生")
    user = _user(p)
    assert "【目标岗位】后端开发实习生" in user and "【所属经历】项目：订单系统（后端开发）" in user
    assert f"【这一句】{H1}" in user and "【问题出在】「负责订单模块的开发」" in user and H2 in user
    assert "张三" not in user and "13812345678" not in user                  # 只发掩码文本
    assert p.checked_section == "改成" and "800" in p.original               # 同一段经历里的数字不算编造


def test_skill_finding_without_an_entry_gets_all_experience():
    finding = {"unit_id": None, **_span("Docker"), "title": "技能「Docker」在经历中没有体现",
               "description": "技能栏列出了「Docker」……", "evidence_quote": "Docker"}
    user = _user(finding_prompt(finding, STRUCTURE, TEXT, MASKED, None))
    assert "【所属经历】全部工作 / 项目经历" in user and "【这一句】熟悉 Java、Docker" in user
    assert "【目标岗位】未指定" in user and H1 in user and H2 in user


def test_gap_prompt_carries_the_jd_quote_the_verdict_and_the_masked_resume():
    item = {"requirement_id": 4, "content": "熟悉 Kafka", "req_type": "hard", "status": "miss",
            "reason": "简历中未提及", "evidence_quote": None, "char_start": None, "char_end": None}
    p = gap_prompt(item, {"id": 4, "quote": "熟悉 Kafka 消息队列"}, TEXT, MASKED, "后端开发实习生")
    user = _user(p)
    assert "【岗位要求】熟悉 Kafka（必须项；JD 原文：「熟悉 Kafka 消息队列」）" in user
    assert "【判定】缺失：简历中未提及" in user and "【简历里相关的原文】无" in user
    assert MASKED in user and "13812345678" not in user and p.checked_section == "怎么补"


def test_numbers_the_source_does_not_have_become_placeholders():
    text = ("【问题】这句没有数字，比如 30 个接口。【改成】响应从 800ms 降到 95ms，支撑 3000 笔订单，"
            "用 Vue3 和 MD5 做【具体做法，如 Top 10 缓存】。【为什么】能提升 30%。")
    fixed, n = fix_numbers(text, "改成", "响应从 800ms 降到 120ms")
    assert n == 2
    assert f"【改成】响应从 800ms 降到 {PLACEHOLDER}ms，支撑 {PLACEHOLDER} 笔订单" in fixed
    assert "Vue3" in fixed and "MD5" in fixed and "Top 10" in fixed        # 名称里的数字、留给用户填的【】都不动
    assert "30 个接口" in fixed and "30%" in fixed                          # 只查【改成】这一段
    assert fix_numbers("没有段标题的一段话 42", "改成", "") == ("没有段标题的一段话 42", 0)


# ───────────── 接口 ─────────────

GOOD_ADVICE = "【问题】「负责系统的优化工作」没说优化了什么。【改成】针对【具体模块】优化，响应从【数值】降到 50ms。【为什么】后端看重量化。"
GAP_ADVICE = "【考察什么】分区、消费者组、积压。【怎么补】如果你做过异步通知，就写成……。【面试怎么答】先讲为什么用 MQ。"


def _events(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def _applied(client, auth_headers, resume_and_job, fake_llm) -> dict:
    """投递一次：诊断只用规则（H_VAGUE 那条会被判"只有做了什么，没有结果"），Kafka 那条要求缺失。"""
    rid, jid = resume_and_job
    fake_llm.replies["_FulltextOut"] = [fulltext_reply((3, "partial", "列表查询响应从 820ms 降至 140ms"), (4, "miss", None))]
    apply_id = apply(client, auth_headers, rid, jid, diagnose_mode="rule_only")["data"]["id"]
    return client.get(f"/api/v1/apply/{apply_id}", headers=auth_headers).json()["data"]


def test_finding_advice_streams_is_checked_saved_and_reused(client, auth_headers, resume_and_job, fake_llm,
                                                           db_session_factory):
    result = _applied(client, auth_headers, resume_and_job, fake_llm)
    finding = next(f for f in result["resume_issues"] if f["rule_code"] == "STAR_INCOMPLETE")
    assert finding["rewrite"] is None
    fake_llm.replies["rewrite"] = [GOOD_ADVICE]

    r = client.post(f"/api/v1/findings/{finding['id']}/advice", headers=auth_headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = _events(r.text)
    assert {name for name, _ in events[:-1]} == {"delta"} and len(events) > 3
    assert "".join(d["text"] for _, d in events[:-1]) == GOOD_ADVICE          # 边生成边下发的是原文
    done = events[-1]
    assert done[0] == "done" and done[1]["violation_count"] == 1              # 50ms 是编的，换成占位符
    assert "降到 【数值】ms" in done[1]["text"] and done[1]["prompt_version"] == "advice-v1"
    sent = fake_llm.calls["rewrite"][0][1][1]
    assert "负责系统的优化工作，持续改进各项功能" in sent and "【目标岗位】后端开发" in sent

    # 存进 findings.rewrite，结果页直接带出来；再点一次不再调模型
    again = client.get(f"/api/v1/apply/{result['id']}", headers=auth_headers).json()["data"]
    assert next(f for f in again["resume_issues"] if f["id"] == finding["id"])["rewrite"]["text"] == done[1]["text"]
    assert _events(client.post(f"/api/v1/findings/{finding['id']}/advice", headers=auth_headers).text) == [done]
    assert len(fake_llm.calls["rewrite"]) == 1


def test_gap_advice_is_saved_on_the_item(client, auth_headers, resume_and_job, fake_llm):
    result = _applied(client, auth_headers, resume_and_job, fake_llm)
    assert [g["requirement_id"] for g in result["gaps"]] == [4, 3] and result["gaps"][0]["advice"] is None
    fake_llm.replies["gap"] = [GAP_ADVICE]

    events = _events(client.post(f"/api/v1/match/{result['id']}/items/4/advice", headers=auth_headers).text)
    assert events[-1] == ("done", {**events[-1][1], "text": GAP_ADVICE, "violation_count": 0})
    sent = fake_llm.calls["gap"][0][1][1]
    assert "【岗位要求】熟悉 Kafka（必须项；JD 原文：「熟悉 Kafka 消息队列」）" in sent and "【判定】缺失" in sent

    gaps = client.get(f"/api/v1/apply/{result['id']}", headers=auth_headers).json()["data"]["gaps"]
    assert gaps[0]["advice"]["text"] == GAP_ADVICE and gaps[1]["advice"] is None   # 只存在那一条上
    items = client.get(f"/api/v1/match/{result['id']}", headers=auth_headers).json()["data"]["items"]
    assert next(i for i in items if i["requirement_id"] == 4)["advice"]["text"] == GAP_ADVICE

    # 已经满足的要求（Redis 由规则判定满足）没有建议可生成
    assert client.post(f"/api/v1/match/{result['id']}/items/2/advice", headers=auth_headers).status_code == 404


def test_model_failure_sends_an_error_saves_nothing_and_can_be_retried(client, auth_headers, resume_and_job, fake_llm,
                                                                       db_session_factory):
    result = _applied(client, auth_headers, resume_and_job, fake_llm)
    fid = next(f["id"] for f in result["resume_issues"])
    fake_llm.replies["rewrite"] = [("【问题】半截", LLMError("超时")), GOOD_ADVICE]

    events = _events(client.post(f"/api/v1/findings/{fid}/advice", headers=auth_headers).text)
    assert events[0] == ("delta", {"text": "【问题】半截"})
    assert events[-1] == ("error", {"code": 50002, "message": "调用大模型失败，请稍后重试"})
    with db_session_factory() as db:
        assert db.get(Finding, fid).rewrite is None

    events = _events(client.post(f"/api/v1/findings/{fid}/advice", headers=auth_headers).text)   # 重试
    assert events[-1][0] == "done"
    with db_session_factory() as db:
        assert db.get(Finding, fid).rewrite["text"] == events[-1][1]["text"]


def test_a_down_model_service_is_named_in_the_error(client, auth_headers, resume_and_job, fake_llm):
    result = _applied(client, auth_headers, resume_and_job, fake_llm)
    fid = next(f["id"] for f in result["resume_issues"])
    fake_llm.replies["rewrite"] = [LLMError("rewrite 调用失败", unavailable="余额不足（402）")]
    events = _events(client.post(f"/api/v1/findings/{fid}/advice", headers=auth_headers).text)
    assert events[-1] == ("error", {"code": 50002, "message": "模型服务暂时不可用，请稍后再试"})


def test_rejections(client, auth_headers, resume_and_job, fake_llm, db_session_factory):
    result = _applied(client, auth_headers, resume_and_job, fake_llm)
    fid = result["resume_issues"][0]["id"]
    other = client.post("/api/v1/auth/register", json={"username": "other", "password": "secret123"}).json()["data"]
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}

    assert client.post(f"/api/v1/findings/{fid}/advice").status_code == 401
    assert client.post(f"/api/v1/findings/{fid}/advice", headers=other_headers).status_code == 404       # 别人的
    assert client.post("/api/v1/findings/999999/advice", headers=auth_headers).status_code == 404
    assert client.post(f"/api/v1/match/{result['id']}/items/4/advice", headers=other_headers).status_code == 404
    assert client.post(f"/api/v1/match/{result['id']}/items/999/advice", headers=auth_headers).status_code == 404

    with db_session_factory() as db:                        # 证据校验没通过的问题不展示，也就没有建议
        db.get(Finding, fid).verify_result = "failed"
        db.commit()
    assert client.post(f"/api/v1/findings/{fid}/advice", headers=auth_headers).status_code == 404
    with db_session_factory() as db:
        assert db.get(MatchReport, result["id"]).items[0].get("advice") is None
