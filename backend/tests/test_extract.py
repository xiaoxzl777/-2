from pathlib import Path

import pytest

from app.parser.extract import EncryptedPdfError, ScannedPdfError, clean_text, extract_pdf

REAL_SAMPLES = sorted((Path(__file__).resolve().parents[2] / "data" / "resumes").glob("*.pdf"))


def test_lines_carry_position_font_and_bold(single_column_pdf):
    r = extract_pdf(single_column_pdf)

    assert r.page_count == 1
    assert r.pages[0].width == pytest.approx(595) and r.pages[0].height == pytest.approx(842)
    assert len(r.lines) == 10  # 姓名 + 2 个标题 + 1 行教育 + 6 行项目

    name = next(l for l in r.lines if l.text == "Zhang San")
    assert name.font_size == 24 and name.is_bold and name.page_no == 1

    heading = next(l for l in r.lines if l.text == "Projects")
    assert heading.font_size == 12 and heading.is_bold

    body = next(l for l in r.lines if l.text.startswith("1."))
    assert body.font_size == 10.5 and not body.is_bold
    assert "Spring Boot" in body.text and "缓存改造" in body.text
    assert 0 <= body.x0 < body.x1 <= 595 and 0 <= body.y0 < body.y1 <= 842


def test_every_line_is_clean_and_nonempty(single_column_pdf):
    for line in extract_pdf(single_column_pdf).lines:
        assert line.text and line.text == line.text.strip()
        assert all(ord(ch) <= 0xFFFF for ch in line.text)


def test_image_only_pdf_is_rejected_as_scanned(image_only_pdf):
    with pytest.raises(ScannedPdfError):
        extract_pdf(image_only_pdf)


def test_encrypted_pdf_is_rejected(encrypted_pdf):
    with pytest.raises(EncryptedPdfError):
        extract_pdf(encrypted_pdf)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("📧 a@b.com", "� a@b.com"),  # 非 BMP → U+FFFD，长度与 JS 一致
        ("  熟悉\tJava　后端 开发  ", "熟悉 Java 后端 开发"),
        ("零​宽﻿字符", "零宽字符"),
    ],
)
def test_clean_text(raw, expected):
    assert clean_text(raw) == expected
    assert all(ord(ch) <= 0xFFFF for ch in clean_text(raw))


@pytest.mark.skipif(not REAL_SAMPLES, reason="data/resumes/ 下没有真实样本（该目录不进 git）")
@pytest.mark.parametrize("pdf", REAL_SAMPLES, ids=lambda p: p.name)
def test_real_samples_extract(pdf):
    r = extract_pdf(pdf)
    assert r.char_count > 300
    assert all(l.text and l.x0 < l.x1 and l.y0 < l.y1 for l in r.lines)
    assert all(1 <= l.page_no <= r.page_count for l in r.lines)
