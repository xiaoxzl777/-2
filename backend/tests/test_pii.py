from pathlib import Path

import pytest

from app.parser.extract import extract_pdf
from app.parser.layout import Block, LayoutResult, PageLayout, analyze_layout, assign_offsets
from app.parser.pii import extract_basics, mask_pii
from app.parser.section import detect_sections

REAL_SAMPLES = sorted((Path(__file__).resolve().parents[2] / "data" / "resumes").glob("*.pdf"))


def _layout(rows: list[tuple]) -> LayoutResult:
    blocks, y = [], 40.0
    for text, size, bold in rows:
        blocks.append(Block(0, 1, 0, 40, y, 300, y + size * 1.3, text, size, bold))
        y += size * 1.3 + 6
    return LayoutResult(blocks, assign_offsets(blocks), [PageLayout(1, "single", 1.0, None)])


def _basics(rows):
    layout = _layout(rows)
    return extract_basics(layout, detect_sections(layout))


def test_extract_basics_from_header():
    b = _basics([("张三", 24, True), ("138-0013-8000 zhangsan@example.com", 10.5, False),
                 ("22 岁 男 现居：广东深圳", 10.5, False),
                 ("教育背景", 12, True), ("某某大学 本科", 10.5, False)])
    assert b.to_dict() == {"name": "张三", "email": "zhangsan@example.com",
                           "phone": "13800138000", "location": "广东深圳"}


def test_name_is_the_largest_name_like_block_not_a_document_title():
    b = _basics([("个人简历", 26, True), ("李四", 20, True), ("后端开发工程师", 10.5, False),
                 ("+86 13912345678", 10.5, False), ("教育背景", 12, True), ("x大学", 10.5, False)])
    assert b.name == "李四" and b.phone == "+8613912345678"


def test_latin_and_minority_names():
    assert _basics([("John A. Smith", 20, True), ("Education", 12, True), ("MIT", 10, False)]).name == "John A. Smith"
    assert _basics([("阿卜杜拉·买买提", 20, True), ("教育背景", 12, True), ("x", 10, False)]).name == "阿卜杜拉·买买提"


def test_basics_never_looks_past_the_header_section():
    # 项目经历里出现的联系邮箱不属于本人基本信息
    b = _basics([("王五", 20, True), ("教育背景", 12, True), ("某某大学", 10.5, False),
                 ("项目经历", 12, True), ("客服邮箱 support@company.com 由本人搭建", 10.5, False)])
    assert b.name == "王五" and b.email is None and b.phone is None


def test_without_any_heading_only_the_first_blocks_are_scanned():
    rows = [("赵六", 20, True), ("zhao@x.com", 10, False)] + [(f"第 {i} 行正文内容", 10, False) for i in range(10)]
    rows.append(("late@x.com", 10, False))
    b = _basics(rows)
    assert b.name == "赵六" and b.email == "zhao@x.com"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("电话 13800138000 邮箱 a.b@qq.com", "电话 XXXXXXXXXXX 邮箱 *.*@**.***"),
        ("Tel: +86 138-0013-8000", "Tel: +XX XXX-XXXX-XXXX"),
        ("身份证 44030119990101123X 。", "身份证 XXXXXXXXXXXXXXXXXX 。"),
        ("QPS 从 200 提升到 1500，P99 由 820ms 降至 140ms", "QPS 从 200 提升到 1500，P99 由 820ms 降至 140ms"),
        ("订单号 20240101123456789 不是电话", "订单号 20240101123456789 不是电话"),
        ("版本 1.13800138000.2", "版本 1.13800138000.2"),
    ],
)
def test_mask_pii(text, expected):
    assert mask_pii(text) == expected
    assert len(mask_pii(text)) == len(text)


def test_mask_name_and_keep_offsets():
    text = "张三\n13800138000 zhangsan@example.com\n项目经历\n张三负责订单服务，使用 Spring Boot 开发"
    masked = mask_pii(text, name="张三")
    assert "张三" not in masked and "13800138000" not in masked and "zhangsan" not in masked
    assert len(masked) == len(text)
    # 长度不变 ⇒ 任意一段在两份文本里的位置完全相同
    start = text.index("使用 Spring Boot")
    assert masked[start:start + 15] == text[start:start + 15]


@pytest.mark.skipif(not REAL_SAMPLES, reason="data/resumes/ 下没有真实样本（该目录不进 git）")
@pytest.mark.parametrize("pdf", REAL_SAMPLES, ids=lambda p: p.name)
def test_real_samples(pdf):
    layout = analyze_layout(extract_pdf(pdf))
    basics = extract_basics(layout, detect_sections(layout))
    assert basics.name and (basics.phone or basics.email)

    masked = mask_pii(layout.full_text, name=basics.name)
    assert len(masked) == len(layout.full_text)
    for secret in (basics.name, basics.phone, basics.email):
        if secret:
            assert secret not in masked
    # 掩码后每个块的偏移依然有效
    assert all(len(masked[b.char_start:b.char_end]) == len(b.text) for b in layout.blocks)
