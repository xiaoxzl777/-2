"""章节兜底：词典认不出的候选交给模型归类。用脚本化的假模型，验证只认编号和类别、"不是标题"并回上一节、失败退回。"""
from app.llm.client import LLMError
from app.parser.layout import Block, LayoutResult, PageLayout, assign_offsets
from app.parser.section import detect_sections
from app.parser.section_llm import classify_sections
from tests.conftest import FakeLLM

BODY = "负责订单服务的开发与性能优化，使用 Spring Boot 与 Redis 完成缓存改造并上线运行。"

# 标题和正文一样大、只是加粗
ROWS = [
    ("张三", 20, True, 0), ("电话 13800000000", 10.5, False, 4),         # 0 1  basics
    ("教育背景", 10.5, True, 16), ("江城大学 本科", 10.5, False, 4),      # 2 3  词典标题
    ("技术沉淀", 10.5, True, 16), (f"1. 张三{BODY}", 10.5, False, 4),     # 4 5  同样式候选
    ("校园二手平台", 10.5, True, 16), (f"2. {BODY}", 10.5, False, 4),     # 6 7  同样式候选（其实是项目名）
    ("开源贡献", 12, True, 16), (f"3. {BODY}", 10.5, False, 4),           # 8 9  字号更大的候选
]


def _layout(rows=ROWS) -> LayoutResult:
    blocks, y = [], 40.0
    for text, size, bold, gap in rows:
        y += gap
        blocks.append(Block(0, 1, 0, 40, y, 40 + len(text) * size * 0.6, y + size * 1.3, text, size, bold))
        y += size * 1.3
    return LayoutResult(blocks, assign_offsets(blocks), [PageLayout(1, "single", 1.0, None)])


def _classify(replies, rows=ROWS):
    layout = _layout(rows)
    llm = FakeLLM(replies)
    result = classify_sections(layout, detect_sections(layout), "张三", llm, ref=("resume", 1))
    return result, llm


def _summary(sections):
    return [(s.type, s.title, s.block_start, s.block_end, s.matched_by, s.needs_llm) for s in sections]


def test_model_decides_each_candidate_and_non_headings_merge_back():
    result, llm = _classify({"_SectionsOut": [
        '{"items": [{"id": 1, "type": "projects"}, {"id": 2, "type": "none"}, {"id": 3, "type": "other"}]}']})

    assert _summary(result.sections) == [
        ("basics", "", 0, 1, "implicit", False),
        ("education", "教育背景", 2, 3, "dict", False),
        ("projects", "技术沉淀", 4, 7, "llm", False),        # 「校园二手平台」不是标题，并进了上一节
        ("other", "开源贡献", 8, 9, "llm", False),
    ]
    assert result.error is None and result.cost > 0

    sent = llm.sent_text
    assert all(t in sent for t in ("[#1] 技术沉淀", "[#2] 校园二手平台", "[#3] 开源贡献", "教育背景"))
    assert "13800000000" not in sent and "张三" not in sent          # 内容先掩码
    assert "1. 某某负责订单服务" in sent                              # 附上了下面内容的开头


def test_invalid_answers_are_ignored_like_no_answer():
    """编号不是候选的、类别不在清单里的都不认：同样式的候选并回上一节，字号更大的仍是待定的 other。"""
    result, _ = _classify({"_SectionsOut": [
        '{"items": [{"id": 9, "type": "projects"}, {"id": 1, "type": "hobby"}]}']})
    assert _summary(result.sections) == [
        ("basics", "", 0, 1, "implicit", False),
        ("education", "教育背景", 2, 7, "dict", False),
        ("other", "开源贡献", 8, 9, "feature", True),
    ]
    assert result.error is None


def test_model_failure_falls_back_without_breaking_the_parse():
    result, _ = _classify({"_SectionsOut": [LLMError("section 调用 deepseek-chat 失败：TimeoutError")]})
    assert [s.title for s in result.sections] == ["", "教育背景", "开源贡献"]
    assert result.sections[-1].needs_llm
    assert result.error.startswith("section:")


def test_bad_json_is_retried_once():
    result, llm = _classify({"_SectionsOut": ["这不是 JSON", '{"items": [{"id": 1, "type": "skills"}]}']})
    assert len(llm.calls["_SectionsOut"]) == 2
    assert [(s.type, s.title) for s in result.sections][2] == ("skills", "技术沉淀")


def test_no_candidates_no_call():
    rows = [("张三", 20, True, 0), ("教育背景", 12, True, 16), ("江城大学 本科", 10.5, False, 4)]
    result, llm = _classify({}, rows)
    assert llm.calls == {} and [s.type for s in result.sections] == ["basics", "education"]


def test_sections_are_rebuilt_after_classification():
    """开头段里的教育只在全文没有教育章节时才切出来；模型把候选归成教育后，就不再切。"""
    rows = [("张三", 20, True, 0), ("江城大学 计算机科学与技术 本科", 10.5, False, 4),
            ("项目经历", 10.5, True, 16), (f"1. {BODY}", 10.5, False, 4),
            ("求学经历", 10.5, True, 16), ("北岭理工大学 硕士", 10.5, False, 4)]
    layout = _layout(rows)
    before = detect_sections(layout)
    assert [s.type for s in before] == ["basics", "education", "projects", "other"]

    result, _ = _classify({"_SectionsOut": ['{"items": [{"id": 1, "type": "education"}]}']}, rows)
    assert [(s.type, s.block_start, s.block_end) for s in result.sections] == [
        ("basics", 0, 1), ("projects", 2, 3), ("education", 4, 5)]
