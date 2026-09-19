"""结构化抽取测试：用脚本化的假 LLM，验证"模型只给编号、文字与区间由服务端推出"这一套逻辑。"""
import pytest

from app.parser.layout import Block, LayoutResult, PageLayout, assign_offsets
from app.parser.pii import extract_basics
from app.parser.section import detect_sections
from app.parser.structure import extract_structure
from tests.conftest import FakeLLM

ROWS = [
    ("张三", 24, True),                                                     # 0
    ("13800138000 zhangsan@example.com", 10.5, False),                      # 1
    ("教育背景", 12, True),                                                  # 2
    ("某某大学 计算机科学与技术 本科 2022.09 - 2026.06", 10.5, False),         # 3
    ("实习经历", 12, True),                                                  # 4
    ("某某科技 后端开发实习生 2025.07 - 至今", 10.5, False),                   # 5
    ("参与用户模块开发，协助完成接口联调。", 10.5, False),                     # 6
    ("项目经历", 12, True),                                                  # 7
    ("二手电商交易平台 全栈开发 2024.01 - 2024.06", 10.5, False),              # 8
    ("技术栈：SpringBoot + Redis + MySQL", 10.5, True),                      # 9
    ("性能优化：", 10.5, True),                                              # 10
    ("热点商品数据预热至 Redis，列表查询响应从 820ms 降至 140ms。", 10.5, False),  # 11
    ("张三独立完成订单模块接口设计。", 10.5, False),                           # 12
    ("专业技能", 12, True),                                                  # 13
    ("熟悉 SpringBoot、MyBatis，了解 Kubernetes", 10.5, False),              # 14
    ("自我评价", 12, True),                                                  # 15
    ("踏实认真，乐于学习。", 10.5, False),                                    # 16
    ("主动了解业务。", 10.5, False),                                         # 17
]


def _layout(rows=ROWS) -> LayoutResult:
    blocks, y = [], 40.0
    for text, size, bold in rows:
        blocks.append(Block(0, 1, 0, 40, y, 500, y + size * 1.3, text, size, bold))
        y += size * 1.3 + (14 if bold and size > 11 else 3)
    return LayoutResult(blocks, assign_offsets(blocks), [PageLayout(1, "single", 1.0, None)])


GOOD = {
    "_EducationOut": ['{"entries": [{"school": "某某大学", "major": "计算机科学与技术", "degree": "本科", "block_ids": [3]}]}'],
    "_ExperienceOut:实习经历": [
        '{"entries": [{"name": "某某科技", "role": "后端开发实习生", "tech_stack": [], "block_ids": [5, 6],'
        ' "highlights": [{"block_ids": [6]}]}]}',
    ],
    "_ExperienceOut:项目经历": [
        # 小标题块 + 正文块 合成一条 highlight
        '{"entries": [{"name": "二手电商交易平台", "role": "全栈开发", "tech_stack": ["SpringBoot", "Redis", "MySQL"],'
        ' "block_ids": [8, 9, 10, 11, 12], "highlights": [{"block_ids": [10, 11]}, {"block_ids": [12]}]}]}',
    ],
    "_SkillsOut": ['{"items": [{"name": "SpringBoot", "level": "熟悉", "block_id": 14},'
                   ' {"name": "MyBatis", "level": "熟悉", "block_id": 14},'
                   ' {"name": "Kubernetes", "level": "了解", "block_id": 14}]}'],
}


def _run(replies=GOOD, rows=ROWS):
    layout = _layout(rows)
    sections = detect_sections(layout)
    llm = FakeLLM(replies)
    result = extract_structure(layout, sections, extract_basics(layout, sections), llm, ref=("resume", 1))
    return layout, llm, result


def test_entries_are_rebuilt_from_block_ids():
    layout, llm, r = _run()
    s, text = r.structure, layout.full_text
    assert r.errors == [] and r.cost > 0

    assert s["basics"]["name"] == "张三" and s["basics"]["phone"] == "13800138000"

    edu = s["education"][0]
    assert (edu["school"], edu["degree"], edu["start"], edu["end"]) == ("某某大学", "本科", "2022-09", "2026-06")
    assert text[edu["char_start"]:edu["char_end"]] == ROWS[3][0]

    work = s["work"][0]
    assert work["kind"] == "internship" and work["is_present"] and (work["start"], work["end"]) == ("2025-07", None)
    assert work["highlights"][0]["text"] == ROWS[6][0]

    project = s["projects"][0]
    assert project["block_ids"] == [8, 9, 10, 11, 12] and project["start"] == "2024-01"
    assert [t["name"] for t in project["tech_stack"]] == ["SpringBoot", "Redis", "MySQL"]
    # highlight 的文字是 full_text 的原样切片；小标题 + 正文合成一条，中间是块之间的换行
    first, second = project["highlights"]
    assert first["text"] == ROWS[10][0] + "\n" + ROWS[11][0] == text[first["char_start"]:first["char_end"]]
    assert second["text"] == ROWS[12][0]

    assert s["summary"]["text"] == ROWS[16][0] + "\n" + ROWS[17][0]          # 自我评价不经过模型
    skills = {k["name"]: k for k in s["skills"]}
    assert set(skills) == {"SpringBoot", "MyBatis", "Kubernetes"} and skills["Kubernetes"]["level"] == "了解"
    k = skills["MyBatis"]
    assert text[k["char_start"]:k["char_end"]] == "MyBatis" and k["skill_id"] is None


def test_pii_never_leaves_the_machine():
    _, llm, _ = _run()
    sent = llm.sent_text
    assert "[#8]" in sent and "[#14]" in sent                     # 确实把带编号的块发出去了
    for secret in ("张三", "13800138000", "zhangsan@example.com"):
        assert secret not in sent
    assert "某某独立完成订单模块接口设计" in sent                   # 正文里的姓名被等长替换
    assert "[#0]" not in sent and "[#1]" not in sent               # basics 章节整个没发
    assert "[#16]" not in sent                                     # 自我评价也没发


def test_invalid_block_ids_are_dropped():
    replies = dict(GOOD)
    replies["_ExperienceOut:实习经历"] = [
        '{"entries": [{"name": "某某科技", "block_ids": [5, 6, 99], "highlights": [{"block_ids": [6]}, {"block_ids": [11]}]},'
        ' {"name": "编造的公司", "block_ids": [8, 9]}]}',           # 8、9 属于项目章节，不属于实习章节
    ]
    _, _, r = _run(replies)
    assert [w["name"] for w in r.structure["work"]] == ["某某科技"]
    work = r.structure["work"][0]
    assert work["block_ids"] == [5, 6] and len(work["highlights"]) == 1


def test_skill_that_is_not_in_its_block_is_a_hallucination():
    replies = dict(GOOD)
    replies["_SkillsOut"] = ['{"items": [{"name": "SpringBoot", "level": null, "block_id": 14},'
                             ' {"name": "Hadoop", "level": "精通", "block_id": 14},'
                             ' {"name": "Redis", "level": null, "block_id": 14},'       # Redis 在别的块里出现过，但不在 14
                             ' {"name": "springboot", "level": null, "block_id": 14}]}']  # 重复
    _, _, r = _run(replies)
    assert [k["name"] for k in r.structure["skills"]] == ["SpringBoot"]


def test_bad_json_is_retried_once_with_the_reason():
    replies = dict(GOOD)
    replies["_EducationOut"] = ["好的，这是结果：学校是某某大学", GOOD["_EducationOut"][0]]
    _, llm, r = _run(replies)
    assert r.errors == [] and r.structure["education"][0]["school"] == "某某大学"
    first, second = llm.calls["_EducationOut"]
    assert len(second) == len(first) + 2
    assert second[-2][0] == "assistant" and "无法使用" in second[-1][1] and "JSON" in second[-1][1]
    assert round(r.cost, 6) == 0.005                                # 4 个章节 + 1 次重试，每次 0.001


def test_a_failing_section_does_not_take_the_others_down():
    replies = dict(GOOD)
    replies["_SkillsOut"] = ["not json", "still not json"]
    _, _, r = _run(replies)
    assert r.structure["skills"] == [] and len(r.errors) == 1 and r.errors[0].startswith("skills:")
    assert r.structure["projects"] and r.structure["education"]


def test_nothing_to_extract_means_no_model_call():
    rows = [("张三", 24, True), ("自我评价", 12, True), ("踏实认真。", 10.5, False)]
    _, llm, r = _run({}, rows)
    assert llm.calls == {} and r.cost == 0 and r.structure["summary"]["text"] == "踏实认真。"


# ───────────── 接进上传流水线之后 ─────────────


def test_structure_is_stored_and_served_after_upload(client, auth_headers, fake_llm, single_column_pdf):
    from tests.conftest import upload_pdf

    # single_column_pdf 的块：0 姓名 / 1 Education / 2 教育行 / 3 Projects / 4–9 六条项目描述
    fake_llm.replies["_ExperienceOut:Projects"] = [
        '{"entries": [{"name": "订单服务", "role": null, "tech_stack": ["Spring Boot", "Redis"],'
        ' "block_ids": [4, 5, 6], "highlights": [{"block_ids": [4]}, {"block_ids": [5]}]}]}']
    rid = upload_pdf(client, auth_headers, single_column_pdf).json()["data"]["id"]

    data = client.get(f"/api/v1/resumes/{rid}/structure", headers=auth_headers).json()["data"]
    assert data["basics"]["name"] == "Zhang San" and data["extraction_errors"] == []
    project = data["projects"][0]
    assert project["name"] == "订单服务" and [h["text"][:2] for h in project["highlights"]] == ["1.", "2."]
    full_text = client.get(f"/api/v1/resumes/{rid}/blocks", headers=auth_headers).json()["data"]["full_text"]
    assert all(full_text[h["char_start"]:h["char_end"]] == h["text"] for h in project["highlights"])


def test_model_outage_fails_the_parse_with_a_readable_reason(client, auth_headers, fake_llm, single_column_pdf):
    from app.llm.client import LLMError
    from tests.conftest import upload_pdf

    fake_llm.replies["_EducationOut"] = [LLMError("connection reset")]
    rid = upload_pdf(client, auth_headers, single_column_pdf).json()["data"]["id"]

    detail = client.get(f"/api/v1/resumes/{rid}", headers=auth_headers).json()["data"]
    assert detail["parse_status"] == "failed" and detail["parse_error"] == "llm_failed"
    r = client.get(f"/api/v1/resumes/{rid}/structure", headers=auth_headers)
    assert r.json()["code"] == 50003 and "大模型" in r.json()["message"]

    # 模型恢复后重新上传同一文件 → 复用那条记录并重新解析成功
    again = upload_pdf(client, auth_headers, single_column_pdf).json()["data"]
    assert again["id"] == rid and again["deduplicated"] is True
    assert client.get(f"/api/v1/resumes/{rid}", headers=auth_headers).json()["data"]["parse_status"] == "success"


@pytest.mark.parametrize("path", ["structure", "blocks"])
def test_structure_and_blocks_are_private(client, auth_headers, single_column_pdf, path):
    from tests.conftest import upload_pdf

    rid = upload_pdf(client, auth_headers, single_column_pdf).json()["data"]["id"]
    other = client.post("/api/v1/auth/register", json={"username": "someone_else", "password": "secret123"})
    headers = {"Authorization": f"Bearer {other.json()['data']['access_token']}"}
    assert client.get(f"/api/v1/resumes/{rid}/{path}", headers=headers).status_code == 404