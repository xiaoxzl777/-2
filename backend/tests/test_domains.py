"""求职方向（领域包）：计算机方向的提示词和改造前逐字一样；换一个方向，提示词、规则、接口都跟着变。"""
import json
import re

import pytest

from app.diagnose.rules import RuleContext, run_rules
from app.domains import DEFAULT, DOMAINS, fill, get_domain
from app.interview import asker
from app.llm import prompts
from app.models import Job
from tests.conftest import apply as _apply, jd_item, jd_reply
from tests.prompt_cases import SNAPSHOT, render_all


def test_cs_prompts_are_byte_identical_to_before():
    """快照是改造前按同样的输入拍的。逐字一样，提示词版本号就不用升，缓存和 M8 的评测结果都还对得上。
    之后只重拍过一次：interview-v2 把面试评分、总结示例里的双花括号改成单花括号（只差花括号）。"""
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert render_all() == snapshot                       # 不传方向：各处的默认值
    assert render_all(DOMAINS["cs"]) == snapshot          # 明确传计算机


@pytest.mark.parametrize("key, recruiter, skill_kind, interviewer", [
    ("ops", "运营岗位招聘官", "专业技能与工具", "运营面试官"),
    ("finance", "财会岗位招聘官", "专业技能与软件", "财会面试官"),
    ("general", "资深招聘官", "专业技能与工具", "的面试官"),
])
def test_switching_direction_changes_every_prompt_and_leaves_no_marks(key, recruiter, skill_kind, interviewer):
    snapshot, other = json.loads(SNAPSHOT.read_text(encoding="utf-8")), render_all(DOMAINS[key])
    assert [k for k in snapshot if other[k] == snapshot[k]] == []
    assert not any("[[" in m[1] for msgs in other.values() for m in msgs)
    assert recruiter in other["diagnose"][0][1] and skill_kind in other["jd_parse"][0][1]
    assert "专业上说得对不对" in other["interview_eval"][0][1] and interviewer in other["interview_ask"][0][1]


def test_no_escaped_braces_reach_the_model():
    """{{ }} 只是 .format() 的转义写法。不经过 .format() 的模板里写了 {{，模型就会收到双花括号（interview-v1 的老毛病）。"""
    for d in DOMAINS.values():
        for case, msgs in render_all(d).items():
            assert not any("{{" in m[1] or "}}" in m[1] for m in msgs), (d.key, case)


def test_every_direction_fills_every_mark():
    marks = {m for v in vars(prompts).values() if isinstance(v, str) for m in re.findall(r"\[\[(\w+)\]\]", v)}
    assert marks
    for d in DOMAINS.values():
        assert marks <= set(d.texts), (d.key, marks - set(d.texts))
        assert set(d.texts) == set(DEFAULT.texts), d.key  # 各方向的片段一一对应，加方向时照着 cs.py 写全


def test_fill_refuses_missing_pieces_and_unknown_directions_fall_back():
    with pytest.raises(KeyError):
        fill("你是[[no_such_piece]]", DEFAULT)
    assert get_domain(None) is DEFAULT and get_domain("law") is DEFAULT    # 老数据、下线的方向按默认处理


def test_rules_turned_off_for_a_direction_are_skipped():
    text = "订单系统\n参与订单模块开发"
    structure = {"projects": [{"name": "订单系统", "char_start": 0, "char_end": len(text),
                               "highlights": [{"char_start": 5, "char_end": len(text)}]}]}
    codes = {f.rule_code for f in run_rules(RuleContext(structure, text))}
    assert codes                                          # 没数字、弱动词，至少触发一条
    kept = {f.rule_code for f in run_rules(RuleContext(structure, text, disabled=frozenset(codes)))}
    assert not codes & kept


def test_interview_opening_line_follows_the_direction():
    assert asker.intro({"company": None}, 5) == "你好，我是这次的技术面试官，今天大概聊 5 个话题。\n"
    assert asker.intro({"company": "示例传媒", "domain": "ops"}, 4).startswith("你好，我是示例传媒的运营面试官")
    assert asker.intro({"company": None, "domain": "general"}, 5).startswith("你好，我是这次的面试官")


# ───────────── 接口 ─────────────


def test_domains_endpoint_lists_the_dropdown(client):
    data = client.get("/api/v1/domains").json()["data"]               # 不用登录
    assert [d["key"] for d in data] == list(DOMAINS) == ["cs", "ops", "finance", "general"]
    cs, ops, finance, general = data
    assert (cs["name"], cs["interview_label"], cs["interviewer"]) == ("计算机", "技术面", "技术面试官")
    assert (ops["name"], ops["interview_label"], ops["interviewer"]) == ("运营", "运营面", "运营面试官")
    assert (finance["name"], finance["interview_label"], finance["interviewer"]) == ("财会金融", "专业面", "财会面试官")
    assert (general["name"], general["interview_label"], general["interviewer"]) == ("其他", "专业面", "面试官")
    assert [d["key"] for d in data if d["note"]] == ["general"]          # 「可能不够准」只有通用方向说
    assert all(d["sample_jd"]["title"] and len(d["sample_jd"]["text"]) >= 30 for d in data)


def test_job_direction_picks_the_jd_prompt_and_is_listed(client, auth_headers, fake_llm):
    fake_llm.replies["_JdOut"] = [jd_reply(jd_item("hard", "skill", "Excel", "会用 Excel 整理数据", "会用 Excel"))]
    body = {"title": "新媒体运营实习生", "domain": "ops",
            "raw_text": "任职要求：会用 Excel 整理数据，熟悉小红书、抖音等平台的内容规则，文字功底好。"}
    job = client.post("/api/v1/jobs", headers=auth_headers, json=body).json()["data"]
    assert job["domain"] == "ops"
    system = fake_llm.calls["_JdOut"][-1][0][1]
    assert "专业技能与工具" in system and "技术技能" not in system
    assert [j["domain"] for j in client.get("/api/v1/jobs", headers=auth_headers).json()["data"]] == ["ops"]
    assert client.post("/api/v1/jobs", headers=auth_headers, json={**body, "domain": "law"}).json()["code"] == 40001


def test_apply_diagnoses_and_matches_by_the_job_direction(client, auth_headers, resume_and_job, fake_llm, db_session_factory):
    rid, jid = resume_and_job
    with db_session_factory() as db:
        db.get(Job, jid).domain = "ops"
        db.commit()
    assert _apply(client, auth_headers, rid, jid)["code"] == 0             # 默认 hybrid：诊断、匹配都会调模型
    sent = fake_llm.sent_text
    assert "运营岗位招聘官" in sent and "运营岗位招聘的简历筛选助手" in sent
    assert "技术招聘官" not in sent and "技术招聘的简历筛选助手" not in sent
