"""版面分析测试。测试 PDF 的每行文字自带编号（L01 / R01 / H1…），阅读顺序的标准答案一目了然。"""
from pathlib import Path

import pytest

from app.parser.extract import extract_pdf
from app.parser.layout import analyze_layout
from tests.conftest import make_pdf

REAL_SAMPLES = sorted((Path(__file__).resolve().parents[2] / "data" / "resumes").glob("*.pdf"))
FILL = " lorem ipsum dolor sit amet consect"  # 把一行撑到接近栏宽


def _tags(result, prefixes=("H", "L", "R", "S")) -> list[str]:
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
    assert not r.needs_llm_fallback


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
    assert not r.needs_llm_fallback
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
