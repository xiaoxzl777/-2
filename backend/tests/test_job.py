"""JD 解析（领域函数）与岗位接口。"""
import json

from app.llm.client import LLMError
from app.matching.jd_parser import parse_jd
from app.matching.skill_dict import SkillDict, SkillEntry
from app.models import Job, Skill
from tests.conftest import FakeLLM

API = "/api/v1/jobs"
JD = """岗位职责：
负责电商平台后端服务的设计与开发。
任职要求：
1. 本科及以上学历，计算机相关专业；
2. 熟悉 Java、SpringBoot，了解 JVM 原理；
3. 熟悉 Redis、MySQL 等常用中间件；
4. 具备良好的沟通能力与团队协作精神；
加分项：有高并发项目经验者优先。"""

SKILLS = SkillDict([SkillEntry(1, "Java", ()), SkillEntry(2, "Spring Boot", ("SpringBoot",)), SkillEntry(3, "Redis", ())])


def _item(req_type, category, skill, quote, content="c"):
    return {"req_type": req_type, "category": category, "skill": skill, "quote": quote, "content": content}


def _reply(*items) -> str:
    return json.dumps({"requirements": list(items)}, ensure_ascii=False)


GOOD_REPLY = _reply(
    _item("hard", "education", None, "本科及以上学历，计算机相关专业", "本科及以上学历"),
    _item("hard", "skill", "Java", "熟悉 Java、SpringBoot"),
    _item("hard", "skill", "SpringBoot", "熟悉 Java、SpringBoot"),
    _item("hard", "skill", "Redis", "熟悉 Redis、MySQL 等常用中间件"),
    _item("hard", "skill", "MySQL", "熟悉 Redis、MySQL 等常用中间件"),
    _item("soft", "other", None, "具备良好的沟通能力与团队协作精神"),
    _item("plus", "experience", None, "有高并发项目经验者优先"),
)


# ───────────── 领域函数 ─────────────


def test_requirements_are_anchored_to_the_jd_and_mapped_to_the_dictionary():
    out = parse_jd("Java 后端", JD, FakeLLM({"_JdOut": [GOOD_REPLY]}), SKILLS)
    reqs = out.requirements
    assert out.error is None and out.rejected == 0 and out.cost == 0.001
    assert [r["id"] for r in reqs] == list(range(1, 8))
    assert all(JD[r["char_start"]:r["char_end"]] == r["quote"] for r in reqs)          # 引用是 JD 原文的精确切片
    assert [(r["skill"], r["skill_id"]) for r in reqs if r["category"] == "skill"] == [
        ("Java", 1), ("SpringBoot", 2), ("Redis", 3), ("MySQL", None)]                  # 别名命中；词典没有的留 None
    assert [r["weight"] for r in reqs] == [1.0, 1.0, 1.0, 1.0, 1.0, 0.3, 0.5]         # 权重由 req_type 决定


def test_fabricated_requirements_are_dropped():
    out = parse_jd("Java 后端", JD, FakeLLM({"_JdOut": [_reply(
        _item("hard", "skill", "Kubernetes", "熟悉 Redis、MySQL 等常用中间件"),          # JD 里根本没提 Kubernetes
        _item("hard", "experience", None, "三年以上大型互联网公司工作经验"),             # 引用是编的
        _item("hard", "skill", "redis", "熟悉 Redis、MySQL 等常用中间件"),              # 大小写不同不算编造
        _item("plus", "skill", "Redis", "熟悉 Redis、MySQL 等常用中间件"),              # 同一技能重复 → 只留第一条
        _item("hard", "other", "Java", "了解 JVM 原理"),                                # 非技能类不带 skill
    )]}), SKILLS)
    assert out.rejected == 2
    assert [(r["id"], r["skill"], r["skill_id"], r["req_type"]) for r in out.requirements] == [
        (1, "redis", 3, "hard"), (2, None, None, "hard")]


def test_malformed_output_is_retried_once_then_reported():
    llm = FakeLLM({"_JdOut": ["我无法处理", GOOD_REPLY]})
    out = parse_jd("Java 后端", JD, llm, SKILLS)
    assert len(out.requirements) == 7 and out.cost == 0.002
    assert "无法使用" in llm.calls["_JdOut"][1][-1][1]

    out = parse_jd("Java 后端", JD, FakeLLM({"_JdOut": ["坏的", '{"requirements": [{"req_type": "must"}]}']}), SKILLS)
    assert out.requirements == [] and out.error


# ───────────── 接口 ─────────────


def _seed_skills(db_session_factory):
    with db_session_factory() as db:
        db.add_all([Skill(canonical_name="Java", category="language", aliases=[]),
                    Skill(canonical_name="Spring Boot", category="framework", aliases=["SpringBoot"]),
                    Skill(canonical_name="Redis", category="middleware", aliases=[])])
        db.commit()


def test_create_list_get_delete(client, auth_headers, db_session_factory, fake_llm):
    _seed_skills(db_session_factory)
    fake_llm.replies["_JdOut"] = [GOOD_REPLY]
    body = {"title": " Java 后端开发 ", "company": "某某科技", "raw_text": "\r\n" + JD.replace("\n", "  \r\n") + "\r\n\r\n"}

    job = client.post(API, headers=auth_headers, json=body).json()["data"]
    assert (job["title"], job["company"], job["is_template"], job["requirement_count"]) == ("Java 后端开发", "某某科技", False, 7)
    assert job["raw_text"] == JD                                                        # 保存前清洗过：区间相对这份文本
    assert all(job["raw_text"][r["char_start"]:r["char_end"]] == r["quote"] for r in job["requirements"])
    assert [r["skill_id"] for r in job["requirements"] if r["skill"]] == [1, 2, 3, None]
    assert JD in fake_llm.sent_text and "Java 后端开发" in fake_llm.sent_text

    listed = client.get(API, headers=auth_headers).json()["data"]
    assert [(j["id"], j["requirement_count"]) for j in listed] == [(job["id"], 7)] and "raw_text" not in listed[0]
    assert client.get(f"{API}/{job['id']}", headers=auth_headers).json()["data"] == job

    assert client.delete(f"{API}/{job['id']}", headers=auth_headers).json()["code"] == 0
    assert client.get(API, headers=auth_headers).json()["data"] == []
    assert client.get(f"{API}/{job['id']}", headers=auth_headers).json()["code"] == 40401


def test_templates_are_visible_to_everyone_but_not_deletable(client, auth_headers, db_session_factory, fake_llm):
    fake_llm.replies["_JdOut"] = [GOOD_REPLY]
    mine = client.post(API, headers=auth_headers, json={"title": "我的岗位", "raw_text": JD}).json()["data"]["id"]
    with db_session_factory() as db:
        template = Job(user_id=None, is_template=True, title="通用后端", raw_text=JD, requirements=[], parse_status="success")
        db.add(template)
        db.commit()
        tid = template.id

    assert [j["id"] for j in client.get(API, headers=auth_headers).json()["data"]] == [mine]
    both = client.get(API, headers=auth_headers, params={"include_templates": 1}).json()["data"]
    assert [(j["id"], j["is_template"]) for j in both] == [(mine, False), (tid, True)]   # 自己的在前
    assert client.get(f"{API}/{tid}", headers=auth_headers).json()["data"]["title"] == "通用后端"
    assert client.delete(f"{API}/{tid}", headers=auth_headers).json()["code"] == 40401

    other = client.post("/api/v1/auth/register", json={"username": "someone_else", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['data']['access_token']}"}
    assert client.get(f"{API}/{mine}", headers=other_headers).json()["code"] == 40401      # 别人的岗位
    assert client.delete(f"{API}/{mine}", headers=other_headers).json()["code"] == 40401
    assert client.get(API, headers=other_headers).json()["data"] == []


def test_failures_save_nothing(client, auth_headers, db_session_factory, fake_llm):
    def post(text=JD):
        return client.post(API, headers=auth_headers, json={"title": "后端", "raw_text": text}).json()

    fake_llm.replies["_JdOut"] = [LLMError("上游超时")]
    assert post()["code"] == 50002
    fake_llm.replies["_JdOut"] = ["坏的", "还是坏的"]
    assert post()["code"] == 50002
    fake_llm.replies["_JdOut"] = [_reply()]                                              # 粘贴的不是 JD：一条要求都没有
    assert post()["code"] == 40001
    fake_llm.replies["_JdOut"] = [_reply(_item("hard", "other", None, "原文里没有的一句话"))]  # 全是编的 → 同上
    assert post()["code"] == 40001

    assert post("太短")["code"] == 40001 and post("x" * 10001)["code"] == 40001
    assert client.post(API, json={"title": "后端", "raw_text": JD}).status_code == 401
    with db_session_factory() as db:
        assert db.query(Job).count() == 0
