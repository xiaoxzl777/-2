from pathlib import Path

import pytest

from app.parser.extract import extract_pdf
from app.parser.layout import Block, LayoutResult, PageLayout, analyze_layout, assign_offsets
from app.parser.section import detect_sections, lookup

REAL_SAMPLES = sorted((Path(__file__).resolve().parents[2] / "data" / "resumes").glob("*.pdf"))
BODY = "负责订单服务的开发与性能优化，使用 Spring Boot 与 Redis 完成缓存改造并上线运行。"


def _layout(rows: list[tuple]) -> LayoutResult:
    """rows: [(text, font_size, is_bold, gap_above)]，自上而下排成单栏。"""
    blocks, y = [], 40.0
    for text, size, bold, gap in rows:
        y += gap
        h = size * 1.3
        blocks.append(Block(0, 1, 0, 40, y, 40 + len(text) * size * 0.6, y + h, text, size, bold))
        y += h
    full_text = assign_offsets(blocks)
    return LayoutResult(blocks, full_text, [PageLayout(1, "single", 1.0, None)])


def _body(n=2):
    return [(f"{i + 1}. {BODY}", 10.5, False, 2) for i in range(n)]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("教育背景", "education"), ("EDUCATION", "education"), ("教育背景 Education", "education"),
        ("Education 教育背景", "education"), ("教育背景/Education", "education"),
        ("一、项目经历", "projects"), ("2. 项目经验", "projects"), ("（三）专业技能", "skills"),
        ("■ 专业技能：", "skills"), ("| 工作经历 |", "work"), ("Work Experience", "work"),
        ("TECHNICAL SKILLS", "skills"), ("自我评价", "summary"), ("获奖情况", "awards"),
        ("Honors and Awards", "awards"), ("求职意向", "basics"), ("兴趣爱好", "other"),
        # 2026-09-27 实测漏掉的写法（补进了词典）
        ("项目展示", "projects"), ("开发经历", "projects"), ("工作履历", "work"), ("校园活动", "work"),
        ("技能证书", "skills"), ("技术专长", "skills"), ("主修课程", "education"),
        # 组合标题：拆开后每部分都认得，取第一部分
        ("专业技能与证书", "skills"), ("技能/证书", "skills"), ("获奖及荣誉", "awards"), ("Awards & Honors", "awards"),
        ("一、项目和工作经历", "projects"), ("学习与工作经历", None),
        # 不是标题
        ("技术栈：SpringBoot + Redis", None), ("核心业务开发：", None), ("Java 项目", None),
        ("项目经历 Experience2024", None), ("负责项目的整体设计", None), ("", None),
    ],
)
def test_lookup(title, expected):
    assert lookup(title) == expected


def test_sections_partition_the_document():
    layout = _layout(
        [("张三", 24, True, 0), ("13800000000 a@b.com", 10.5, False, 8),
         ("教育背景", 12, True, 20), ("某某大学 计算机科学与技术 本科", 10.5, False, 6),
         ("项目经历", 12, True, 20), *_body(3),
         ("专业技能", 12, True, 20), *_body(2),
         ("自我评价", 12, True, 20), ("踏实认真，乐于学习。", 10.5, False, 6)]
    )
    sections = detect_sections(layout)

    assert [s.type for s in sections] == ["basics", "education", "projects", "skills", "summary"]
    assert sections[0].title == "" and sections[0].matched_by == "implicit"
    assert [s.title for s in sections[1:]] == ["教育背景", "项目经历", "专业技能", "自我评价"]
    assert all(s.confidence == 1.0 and s.matched_by == "dict" for s in sections[1:])

    # 章节恰好把全部块切成连续的几段，没有遗漏也没有重叠
    assert sections[0].block_start == 0 and sections[-1].block_end == len(layout.blocks) - 1
    for a, b in zip(sections, sections[1:]):
        assert b.block_start == a.block_end + 1
    for s in sections:
        first, last = layout.blocks[s.block_start], layout.blocks[s.block_end]
        assert (s.char_start, s.char_end) == (first.char_start, last.char_end)
        assert layout.full_text[s.char_start:s.char_end].startswith(first.text)

    projects = sections[2]
    assert layout.full_text[projects.content_start:projects.char_end].startswith("1. ")
    assert projects.to_dict()["type"] == "projects"


def test_headings_with_same_font_size_are_found_by_dictionary_alone():
    """很多简历的标题只是加粗、字号与正文相同，甚至连加粗都没有。"""
    layout = _layout([("张三", 10.5, False, 0), ("教育经历", 10.5, False, 2), *_body(1),
                      ("实习经历", 10.5, True, 2), *_body(2)])
    sections = detect_sections(layout)
    assert [s.type for s in sections] == ["basics", "education", "work"]
    assert sections[1].confidence < sections[2].confidence <= 1.0


def test_work_kind():
    layout = _layout([("工作经历", 12, True, 0), *_body(1), ("实习经历", 12, True, 20), *_body(1),
                      ("校园经历", 12, True, 20), *_body(1), ("Internship Experience", 12, True, 20), *_body(1)])
    assert [(s.type, s.kind) for s in detect_sections(layout)] == [
        ("work", "work"), ("work", "internship"), ("work", "campus"), ("work", "internship")]


def test_bold_subheadings_inside_a_project_are_not_sections():
    layout = _layout(
        [("项目经历", 12, True, 0),
         ("二手电商交易平台 全栈开发 2024.01-2024.06", 10.5, False, 8),
         ("技术栈：SpringBoot + Redis + MySQL", 10.5, True, 2),
         ("核心业务开发：", 10.5, True, 8), *_body(1),
         ("性能优化：", 10.5, True, 8), *_body(1),
         ("RAG 检索方案", 10.5, True, 8), *_body(1)]
    )
    sections = detect_sections(layout)
    assert len(sections) == 1 and sections[0].type == "projects"
    assert sections[0].block_end == len(layout.blocks) - 1


def test_unknown_large_heading_becomes_other_and_asks_for_llm():
    layout = _layout([("张三", 24, True, 0),                      # 页顶大号姓名：属于 basics，不是标题
                      ("教育背景", 12, True, 20), *_body(1),
                      ("开源贡献", 12, True, 20), *_body(2)])       # 词典不认识，但版面上明显是标题
    sections = detect_sections(layout)
    assert [s.type for s in sections] == ["basics", "education", "other"]
    other = sections[-1]
    assert other.title == "开源贡献" and other.matched_by == "feature" and other.needs_llm
    assert 0.6 <= other.confidence < 1.0


def test_lines_styled_like_dictionary_headings_become_candidates():
    """标题和正文一样大、只是加粗：和词典标题同样式的短行记为候选（style），交给模型判断；不加粗的短行不算。"""
    layout = _layout([("张三", 10.5, False, 0), ("教育背景", 10.5, True, 12), *_body(1),
                      ("技术沉淀", 10.5, True, 12), *_body(2),             # 词典不认识，和标题同样式
                      ("校园二手平台", 10.5, True, 12), *_body(1),         # 项目名也是这个样式：交给模型说"不是标题"
                      ("负责接口开发", 10.5, False, 12), *_body(1)])       # 普通短行：不是候选
    sections = detect_sections(layout)
    assert [(s.type, s.title, s.matched_by, s.needs_llm) for s in sections] == [
        ("basics", "", "implicit", False), ("education", "教育背景", "dict", False),
        ("other", "技术沉淀", "style", True), ("other", "校园二手平台", "style", True),
    ]


def test_no_style_candidates_when_headings_look_like_body_text():
    layout = _layout([("张三", 10.5, False, 0), ("教育背景", 10.5, False, 12), *_body(1),
                      ("技术沉淀", 10.5, False, 12), *_body(1)])
    assert [s.type for s in detect_sections(layout)] == ["basics", "education"]


def test_untitled_education_at_the_end_of_the_header_becomes_education():
    rows = [("张三", 20, True, 0), ("电话 13800000000 邮箱 zs@example.com", 10.5, False, 4),
            ("江城大学 计算机科学与技术 本科 2022.09-2026.06", 10.5, False, 4),
            ("项目经历", 12, True, 20), *_body(1)]
    sections = detect_sections(_layout(rows))
    assert [(s.type, s.block_start, s.block_end) for s in sections] == [
        ("basics", 0, 1), ("education", 2, 2), ("projects", 3, 4)]

    # 全文已经有教育章节 → 不切
    with_edu = rows + [("教育背景", 12, True, 20), ("北岭理工大学 硕士", 10.5, False, 4)]
    assert [s.type for s in detect_sections(_layout(with_edu))] == ["basics", "projects", "education"]

    # 带联系方式、住址的一块留在 basics：切走了本地就抽不到，还会被发给模型
    for line in ["江城大学 本科 电话 13800000000", "地址：北京市海淀区学院路 30 号", "现居：江城市大学城 18 栋"]:
        rows = [("张三", 20, True, 0), (line, 10.5, False, 4), ("项目经历", 12, True, 20), *_body(1)]
        assert [s.type for s in detect_sections(_layout(rows))] == ["basics", "projects"], line


def test_table_resume_sections_come_from_the_label_column(table_resume_pdf):
    """表格型简历把章节名放在左列：表格按行展开时左格单独成块，章节才认得出来。
    教育表上方没有标题：开头段末尾的教育行切出来当作教育章节，表头「时间 学校 专业 学历」留在 basics。"""
    layout = analyze_layout(extract_pdf(table_resume_pdf))
    sections = detect_sections(layout)
    assert [(s.type, s.title, s.matched_by) for s in sections] == [
        ("basics", "", "implicit"), ("education", "", "implicit"), ("projects", "项目经历", "dict"),
        ("skills", "专业技能", "dict"), ("awards", "获奖情况", "dict"),
    ]
    edu = sections[1]
    assert [b.text for b in layout.blocks[edu.block_start:edu.block_end + 1]] == ["2022.09-2026.06 江城大学 计算机科学与技术 本科"]
    assert edu.content_start == edu.char_start


def test_document_without_any_heading():
    sections = detect_sections(_layout(_body(4)))
    assert len(sections) == 1
    assert sections[0].type == "other" and sections[0].confidence == 0.0
    assert detect_sections(LayoutResult([], "", [])) == []


@pytest.mark.skipif(not REAL_SAMPLES, reason="data/resumes/ 下没有真实样本（该目录不进 git）")
@pytest.mark.parametrize("pdf", REAL_SAMPLES, ids=lambda p: p.name)
def test_real_samples(pdf):
    layout = analyze_layout(extract_pdf(pdf))
    sections = detect_sections(layout)
    types = [s.type for s in sections]
    assert types[0] == "basics" and len(set(types) & {"education", "work", "projects", "skills"}) >= 2
    assert sections[0].block_start == 0 and sections[-1].block_end == len(layout.blocks) - 1
    for a, b in zip(sections, sections[1:]):
        assert b.block_start == a.block_end + 1
