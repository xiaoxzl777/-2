"""版面分析测试。测试 PDF 的每行文字自带编号（L01 / R01 / H1…），阅读顺序的标准答案一目了然。"""
from pathlib import Path

import pytest

from app.parser.extract import extract_pdf
from app.parser.layout import analyze_layout
from tests.conftest import make_pdf, table_grid

REAL_SAMPLES = sorted((Path(__file__).resolve().parents[2] / "data" / "resumes").glob("*.pdf"))
FILL = " lorem ipsum dolor sit amet consect"  # 把一行撑到接近栏宽


def _tags(result, prefixes=("H", "L", "R", "S", "T")) -> list[str]:
    """按输出顺序取出每个块开头的编号。"""
    out = []
    for b in result.blocks:
        for head in b.text.split()[:2]:                     # 编号可能跟在项目符号后面
            if head[0] in prefixes and head[1:].isdigit():
                out.append(head)
                break
    return out


def _two_column_items(left_x=40, right_x=315, n=12, top=130):
    items = [
        (245, 50, "H1 Zhang San", 20, "hebo"),          # 居中大标题，压住中缝 → 跨栏行
        (150, 80, "H2 13800000000", 10, "helv"),        # 电话与邮箱分居中缝两侧、都没压住它
        (340, 80, "H3 zhangsan@example.com", 10, "helv"),
    ]
    for i in range(n):
        y = top + i * 30                                  # 行距大，每行自成一块
        items.append((left_x, y, f"L{i + 1:02d}{FILL}", 10, "helv"))
        items.append((right_x, y, f"R{i + 1:02d}{FILL}", 10, "helv"))
    return items


def test_two_columns_read_left_then_right_with_header_first(tmp_path):
    r = analyze_layout(extract_pdf(make_pdf(tmp_path / "two.pdf", _two_column_items())))

    expected = ["H1", "H2"] + [f"L{i:02d}" for i in range(1, 13)] + [f"R{i:02d}" for i in range(1, 13)]
    tags = _tags(r)
    assert tags == expected, tags
    # 电话与邮箱在同一水平线上 → 合并为一行，且排在两栏正文之前
    header = next(b for b in r.blocks if b.text.startswith("H2"))
    assert "H3 zhangsan@example.com" in header.text and header.column_index == -1

    page = r.pages[0]
    assert page.layout_type == "double" and page.confidence >= 0.8
    assert 200 < page.gap[0] < page.gap[1] <= 316           # 左栏行尾 ~214，右栏起点 315
    assert {b.column_index for b in r.blocks if b.text[0] == "L"} == {0}
    assert {b.column_index for b in r.blocks if b.text[0] == "R"} == {1}
    assert r.layout_confidence >= 0.7


def test_sidebar_layout(tmp_path):
    items = [(30, 60 + i * 30, f"S{i + 1:02d} skill item", 10, "helv") for i in range(10)]
    items += [(200, 60 + i * 30, f"R{i + 1:02d}{FILL}{FILL}", 10, "helv") for i in range(14)]
    r = analyze_layout(extract_pdf(make_pdf(tmp_path / "side.pdf", items)))

    assert _tags(r) == [f"S{i:02d}" for i in range(1, 11)] + [f"R{i:02d}" for i in range(1, 15)]
    assert r.pages[0].layout_type == "sidebar"


def test_right_aligned_dates_do_not_make_a_second_column(tmp_path):
    """单栏简历里"公司名 …… 2023.09-2024.06"的右对齐日期，不能被当成右栏。"""
    items = []
    y = 60
    for k in range(5):
        items.append((40, y, f"L{k * 4 + 1:02d} Company {k}", 10, "hebo"))
        items.append((460, y, "2023.09-2024.06", 10, "helv"))
        for j in range(3):
            y += 16
            items.append((40, y, f"- L{k * 4 + 2 + j:02d}{FILL}{FILL}{FILL}", 10, "helv"))   # 项目符号 → 各自成块
        y += 30
    r = analyze_layout(extract_pdf(make_pdf(tmp_path / "dates.pdf", items)))

    assert r.pages[0].layout_type == "single"
    assert r.layout_confidence >= 0.7
    assert _tags(r) == [f"L{i:02d}" for i in range(1, 21)]
    first = next(b for b in r.blocks if b.text.startswith("L01"))
    assert first.text.endswith("2023.09-2024.06")          # 日期并回了所在行


def test_wrapped_lines_merge_but_bullets_split(tmp_path):
    full = "x" * 100                                        # 写满整行 → 下一行是折行
    items = [
        (40, 100, f"1. {full}", 10, "helv"),
        (40, 114, "continues here", 10, "helv"),
        (40, 128, f"2. {full}", 10, "helv"),
        (40, 142, "also continues", 10, "helv"),
        (40, 156, "3. short item", 10, "helv"),
        (40, 170, "4. another short item", 10, "helv"),
    ] + [(40, 200 + i * 14, f"pad {i} {full}", 10, "helv") for i in range(3)]
    r = analyze_layout(extract_pdf(make_pdf(tmp_path / "wrap.pdf", items)))

    texts = [b.text for b in r.blocks]
    assert texts[0].startswith("1. ") and texts[0].endswith("continues here")
    assert texts[1].startswith("2. ") and texts[1].endswith("also continues")
    assert texts[2] == "3. short item" and texts[3] == "4. another short item"


def test_labeled_list_items_split_even_when_the_previous_item_fills_the_line(tmp_path):
    full = "掌握服务注册发现与远程调用以及网关路由转发并且使用过限流组件实现接口降级与限流保护整体稳定"
    items = [
        (40, 100, f"微服务：{full}", 10.5, "china-s"),              # 写满整行，但它已经是完整的一项
        (40, 116, f"缓存与分布式：{full}", 10.5, "china-s"),         # 下一项：以"标签："开头 → 另起一块
        (40, 132, "并建立多级缓存减少数据库压力", 10.5, "china-s"),   # 这才是折行
        (40, 148, f"在此期间我们还{full}", 10.5, "china-s"),      # 普通段落（短行之后另起）
        (40, 164, "模块：用户与订单", 10.5, "china-s"),               # 段落里碰巧以"xx："起头的折行 → 不拆
    ]
    r = analyze_layout(extract_pdf(make_pdf(tmp_path / "labels.pdf", items)))
    texts = [b.text for b in r.blocks]
    assert texts == [f"微服务：{full}", f"缓存与分布式：{full}并建立多级缓存减少数据库压力",
                     f"在此期间我们还{full}模块：用户与订单"]
    _assert_contract(r)


def test_title_row_with_right_aligned_date_does_not_swallow_next_line(tmp_path):
    body = "y" * 100
    items = [
        (40, 100, "Project Alpha", 10, "helv"), (470, 100, "2024.01-2024.06", 10, "helv"),
        (40, 114, "Tech stack: Spring Boot, Redis", 10, "helv"),
    ] + [(40, 140 + i * 14, f"- {body}", 10, "helv") for i in range(3)]
    r = analyze_layout(extract_pdf(make_pdf(tmp_path / "title.pdf", items)))
    assert r.blocks[0].text == "Project Alpha 2024.01-2024.06"
    assert r.blocks[1].text == "Tech stack: Spring Boot, Redis"


def test_chinese_wrap_joins_without_space(tmp_path):
    full = "负责订单服务的开发与性能优化使用缓存完成改造并上线支撑大促流量峰值期间稳定运行并且持续迭代"
    items = [(40, 100, full, 10.5, "china-s"), (40, 116, "保证了系统可用性", 10.5, "china-s")]
    items += [(40, 150 + i * 16, full, 10.5, "china-s") for i in range(3)]
    r = analyze_layout(extract_pdf(make_pdf(tmp_path / "zh.pdf", items)))
    assert r.blocks[0].text == full + "保证了系统可用性"


def test_page_numbers_and_repeated_headers_are_dropped(tmp_path):
    import pymupdf

    doc = pymupdf.open()
    for p in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_text((40, 30), "Zhang San Resume", fontsize=9, fontname="helv")     # 每页重复的页眉
        page.insert_text((290, 825), f"{p + 1} / 2", fontsize=9, fontname="helv")        # 页码
        for i in range(8):
            page.insert_text((40, 100 + i * 30), f"L{p * 8 + i + 1:02d}{FILL}{FILL}", fontsize=10, fontname="helv")
    path = tmp_path / "pages.pdf"
    doc.save(path)
    r = analyze_layout(extract_pdf(path))

    assert "Zhang San Resume" not in r.full_text and "/ 2" not in r.full_text
    assert _tags(r) == [f"L{i:02d}" for i in range(1, 17)]
    assert [b.page_no for b in r.blocks] == [1] * 8 + [2] * 8


# ───────────────────────── 时间轴 ─────────────────────────


def test_timeline_date_column_is_read_row_by_row(tmp_path):
    """左边一列日期、右边同一行是经历标题：按行读，日期跟着它那条经历，不当成两栏先左后右。"""
    items = [(40, 60, "Zhang San", 18, "hebo"), (40, 90, "Experience", 13, "hebo")]
    y = 115
    for k in range(4):
        items.append((40, y, f"202{k}.07-202{k}.09", 10, "helv"))
        items.append((160, y, f"E{k + 1} Company {k} backend intern", 10, "helv"))
        for j in range(2):
            y += 15
            items.append((160, y, f"- E{k + 1}.{j + 1} built the order service", 10, "helv"))
        y += 23
    path = make_pdf(tmp_path / "timeline.pdf", items)

    r = analyze_layout(extract_pdf(path))
    texts = [b.text for b in r.blocks]
    assert texts[2:5] == ["2020.07-2020.09 E1 Company 0 backend intern",
                          "- E1.1 built the order service", "- E1.2 built the order service"]
    assert texts[5].startswith("2021.07-2021.09 E2")
    assert r.pages[0].layout_type == "single" and r.layout_confidence >= 0.7
    _assert_contract(r)

    # 关掉这条规则（最初的算法）：先读完所有日期，再读经历，而且自报是有把握的侧边栏
    r0 = analyze_layout(extract_pdf(path), date_columns=False)
    assert [b.text for b in r0.blocks][2:6] == [f"202{k}.07-202{k}.09" for k in range(4)]
    assert r0.pages[0].layout_type == "sidebar" and r0.pages[0].confidence == 1.0


@pytest.mark.parametrize(("text", "expected"), [
    ("2023.07-2023.09", True), ("2024.05 - 至今", True), ("2022年9月", True),
    ("2022 年 优秀学生干部", False),          # 奖项里带年份：侧边栏的获奖列表不能被当成日期列
    ("负责 2023 年的订单系统", False), ("Spring Boot", False),
])
def test_date_line(text, expected):
    from app.parser.layout import _is_date_line
    assert _is_date_line(text) is expected


# ───────────────────────── 表格 ─────────────────────────


def test_bordered_table_reads_row_by_row(tmp_path):
    """表格的列间空白不能当成栏间空白：按行读，一行一块；页面仍是单栏。"""
    body = "负责订单服务的开发与性能优化，使用 Spring Boot 与 Redis 完成缓存改造并上线"
    items, rects, bottom = table_grid(40, 130, [170, 180, 165], [
        ["时间", "学校", "专业"],
        ["2022.09-2026.06", "江城大学", "计算机科学与技术"],
        ["2019.09-2022.06", "江城一中", "理科"],
        ["2025.07-2025.09", "北岭暑期学校", "机器学习"],
    ])
    items += [(250, 60, "张三", 20, "china-s"), (40, 120, "教育背景", 12, "china-s"),
              (40, bottom + 30, "项目经历", 12, "china-s")]
    items += [(40, bottom + 50 + i * 16, f"{i + 1}. {body}", 10, "china-s") for i in range(5)]
    r = analyze_layout(extract_pdf(make_pdf(tmp_path / "table.pdf", items, rects=rects)))

    texts = [b.text for b in r.blocks]
    i = texts.index("教育背景")
    assert texts[i + 1:i + 6] == ["时间 学校 专业", "2022.09-2026.06 江城大学 计算机科学与技术",
                                  "2019.09-2022.06 江城一中 理科", "2025.07-2025.09 北岭暑期学校 机器学习", "项目经历"]
    assert r.pages[0].layout_type == "single" and r.layout_confidence >= 0.7
    assert {b.column_index for b in r.blocks} == {0}
    _assert_contract(r)


def test_table_resume(table_resume_pdf):
    """整页表格：页面判为 table；左列的章节名单独成块，多行的格子照常按行分块；超出格子的字仍归自己的格子。"""
    r = analyze_layout(extract_pdf(table_resume_pdf))

    assert [b.text for b in r.blocks] == [
        "个人简历",
        "姓名 张三 性别 男", "电话 13800000000 邮箱 zs@example.com",
        "时间 学校 专业 学历", "2022.09-2026.06 江城大学 计算机科学与技术 本科",
        "项目经历", "校园二手交易平台（2024.03-2024.06）", "1. 负责订单模块与支付回调", "2. 用 Redis 缓存热门商品",
        "专业技能", "Java、Spring Boot、MySQL、Redis",
        "获奖情况", "2024 年蓝桥杯省二等奖",
    ]
    assert r.pages[0].layout_type == "table" and r.layout_confidence == 1.0
    _assert_contract(r)


def test_vertically_merged_label_cell_becomes_its_own_block(tmp_path):
    items, rects, _ = table_grid(40, 100, [90, 165, 260], [
        ["教育背景", "2022.09-2026.06", "江城大学"],
        [None, "2019.09-2022.06", "江城一中"],
        ["获奖情况", "2024.05", "蓝桥杯省二等奖"],
        [None, "2023.11", "校程序设计竞赛一等奖"],
    ])
    items.append((40, 300, "自我评价：热爱编程，做事认真负责，能快速学习新技术并用在项目中。", 10, "china-s"))  # 凑够字数，免得被当成扫描件
    r = analyze_layout(extract_pdf(make_pdf(tmp_path / "merged.pdf", items, rects=rects)))

    assert [b.text for b in r.blocks][:6] == [
        "教育背景", "2022.09-2026.06 江城大学", "2019.09-2022.06 江城一中",
        "获奖情况", "2024.05 蓝桥杯省二等奖", "2023.11 校程序设计竞赛一等奖",
    ]


def test_table_in_the_right_column_stays_in_that_column(tmp_path):
    """表格先缩成一整块参与分栏：落在右栏里就排在右栏的上下文之间，不影响左栏。"""
    items = [(40, 130 + i * 30, f"L{i + 1:02d}{FILL}", 10, "helv") for i in range(12)]
    items += [(315, 130 + i * 30, f"R{i + 1:02d}{FILL}", 10, "helv") for i in range(4)]
    table, rects, bottom = table_grid(315, 240, [60, 90, 90], [
        ["T1", "Java", "Python"], ["T2", "MySQL", "Redis"], ["T3", "Git", "Docker"],
    ], font="helv")
    items += table + [(315, bottom + 30 + i * 30, f"R{i + 5:02d}{FILL}", 10, "helv") for i in range(4)]
    r = analyze_layout(extract_pdf(make_pdf(tmp_path / "two_table.pdf", items, rects=rects)))

    assert _tags(r) == ([f"L{i:02d}" for i in range(1, 13)] + ["R01", "R02", "R03", "R04"]
                        + ["T1", "T2", "T3"] + ["R05", "R06", "R07", "R08"])
    assert next(b for b in r.blocks if b.text.startswith("T1")).text == "T1 Java Python"
    assert {b.column_index for b in r.blocks if b.text[0] == "T"} == {1}
    assert r.pages[0].layout_type == "double"


def test_background_color_blocks_are_not_a_table(tmp_path):
    """顶部色条 + 侧边栏底色块会被 find_tables 拼成一张 2×2 的"表"，但有字的格子太少，不算表格。"""
    items = [(30, 50, "S00 Zhang San", 16, "hebo")]
    items += [(30, 120 + i * 30, f"S{i + 1:02d} skill item", 10, "helv") for i in range(10)]
    items += [(200, 120 + i * 30, f"R{i + 1:02d}{FILL}{FILL}", 10, "helv") for i in range(14)]
    path = make_pdf(tmp_path / "frame.pdf", items, fills=[(0, 0, 595, 90), (0, 90, 185, 842)])
    extracted = extract_pdf(path)
    assert extracted.tables, "这个用例要求 find_tables 确实把色块认成了表格"

    r = analyze_layout(extracted)
    assert _tags(r) == [f"S{i:02d}" for i in range(0, 11)] + [f"R{i:02d}" for i in range(1, 15)]
    assert r.pages[0].layout_type == "sidebar"


def _assert_contract(r):
    """系统不变量②：每个块都是 full_text 的精确切片，块之间恰好隔一个换行。"""
    assert r.blocks, "没有任何块"
    for i, b in enumerate(r.blocks):
        assert b.block_index == i
        assert r.full_text[b.char_start:b.char_end] == b.text
        assert "\n" not in b.text and b.text == b.text.strip() and b.text
    for a, b in zip(r.blocks, r.blocks[1:]):
        assert b.char_start == a.char_end + 1 and r.full_text[a.char_end] == "\n"
    assert r.blocks[-1].char_end == len(r.full_text)


def test_full_text_contract(tmp_path, single_column_pdf):
    _assert_contract(analyze_layout(extract_pdf(single_column_pdf)))
    _assert_contract(analyze_layout(extract_pdf(make_pdf(tmp_path / "two.pdf", _two_column_items()))))


@pytest.mark.skipif(not REAL_SAMPLES, reason="data/resumes/ 下没有真实样本（该目录不进 git）")
@pytest.mark.parametrize("pdf", REAL_SAMPLES, ids=lambda p: p.name)
def test_real_samples(pdf):
    r = analyze_layout(extract_pdf(pdf))
    _assert_contract(r)
    # 页面最上方的内容必须排在最前（PyMuPDF 原生顺序会把页顶姓名放到最后）
    top = min(r.blocks, key=lambda b: (b.page_no, b.y0))
    assert top.block_index == 0
