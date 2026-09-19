"""测试用 PDF 由代码现场生成，不依赖任何真实简历文件。"""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

A4 = (595, 842)


def make_pdf(path: Path, items: list[tuple], *, encrypt: bool = False) -> Path:
    """items: [(x, y, text, fontsize, fontname)]；fontname: 'china-s' 中文, 'helv' 常规, 'hebo' 加粗。"""
    doc = pymupdf.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    for x, y, text, size, font in items:
        page.insert_text((x, y), text, fontsize=size, fontname=font)
    if encrypt:
        doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    else:
        doc.save(path)
    doc.close()
    return path


@pytest.fixture
def single_column_pdf(tmp_path) -> Path:
    body = "负责订单服务的开发与性能优化，使用 Spring Boot 与 Redis 完成缓存改造并上线，"
    items = [
        (250, 60, "Zhang San", 24, "hebo"),
        (40, 120, "Education", 12, "hebo"),
        (40, 140, "某某大学 计算机科学与技术 本科 2023.09-2027.06", 10.5, "china-s"),
        (40, 180, "Projects", 12, "hebo"),
    ]
    items += [(40, 200 + i * 16, f"{i + 1}. {body}", 10.5, "china-s") for i in range(6)]
    return make_pdf(tmp_path / "single.pdf", items)


@pytest.fixture
def image_only_pdf(tmp_path) -> Path:
    """模拟扫描件：页面上只有一张图，没有文本层。"""
    doc = pymupdf.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), False)
    pix.clear_with(200)
    page.insert_image(pymupdf.Rect(50, 50, 545, 792), pixmap=pix)
    path = tmp_path / "scanned.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def encrypted_pdf(tmp_path) -> Path:
    return make_pdf(tmp_path / "enc.pdf", [(40, 100, "secret resume " * 20, 10.5, "helv")], encrypt=True)
