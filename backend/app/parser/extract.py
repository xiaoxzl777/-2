"""PDF 文本抽取：把每一页变成带坐标的"行"。

为什么以"行"为单位而不是 PyMuPDF 的 block：
- PyMuPDF 的 block 经常把一整节（十几行）并成一块，粒度太粗，无法做到"一条经历一个单元"；
- block 的输出顺序也不可靠（页面顶部的姓名可能排在最后）。
所以这里只忠实地抽出行，阅读顺序与分块交给 layout.py。

带边框的表格用 PyMuPDF 的 find_tables() 找，但只取格子的位置；格子里的文字仍以抽出的行为准，
因为 find_tables 按格子边界裁字，文字超出格子时一个日期会被切成两半。

本模块是领域层：输入文件路径，输出纯数据，不碰数据库。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.config import settings

logger = logging.getLogger("app.parse")

# find_tables 第一次调用时会打印一句"推荐安装 pymupdf_layout"，关掉
pymupdf.no_recommend_layout()

# 偏移以 Unicode 码点计。把非 BMP 字符（emoji、部分图标字体）替换掉，
# 保证 Python 的 len() 与前端 JS 的 .length 一致，高亮不会错位。
_NON_BMP = re.compile(r"[\U00010000-\U0010FFFF]")
_REPLACEMENT = "�"
# 不可见控制字符（保留 \t，后面统一转空格）
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‏﻿]")

_BOLD_FLAG = 1 << 4  # PyMuPDF span flags：bit 4 = bold


class ScannedPdfError(Exception):
    """PDF 没有可用的文本层（扫描件 / 图片型简历）。"""


class EncryptedPdfError(Exception):
    """PDF 已加密，需要密码。"""


@dataclass(slots=True)
class Line:
    """页面上的一行文字。坐标单位为 PDF point，原点在页面左上角。"""

    page_no: int  # 从 1 开始
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    font_size: float  # 该行内按字符数加权的主字号
    is_bold: bool  # 该行加粗字符是否过半

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(slots=True)
class PageInfo:
    page_no: int
    width: float
    height: float
    image_count: int


Box = tuple[float, float, float, float]


@dataclass(slots=True)
class TableBox:
    """一张带边框的表格，只有格子的位置。"""

    page_no: int
    bbox: Box
    rows: list[list[Box]]  # 自上而下每一行的格子，从左到右；合并的格子只出现在它最上面那一行


@dataclass(slots=True)
class ExtractResult:
    lines: list[Line]
    pages: list[PageInfo]
    ats_signals: dict[str, int] = field(default_factory=dict)
    tables: list[TableBox] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def char_count(self) -> int:
        return sum(len(line.text) for line in self.lines)


def clean_text(s: str) -> str:
    """唯一允许的文本清洗点：偏移一旦算出，任何地方都不得再改动文本。"""
    s = _NON_BMP.sub(_REPLACEMENT, s)
    s = _CONTROL.sub("", s)
    s = s.replace("\t", " ").replace(" ", " ").replace("　", " ")
    return s.strip()


def _line_from_spans(page_no: int, raw_line: dict) -> Line | None:
    spans = [s for s in raw_line["spans"] if s["text"].strip()]
    if not spans:
        return None
    text = clean_text("".join(s["text"] for s in raw_line["spans"]))
    if not text:
        return None

    total = sum(len(s["text"]) for s in spans)
    bold = sum(len(s["text"]) for s in spans if s["flags"] & _BOLD_FLAG or "bold" in s["font"].lower())
    # 主字号：按字符数加权取最多的那个，避免行首一个大号项目符号带偏
    by_size: dict[float, int] = {}
    for s in spans:
        size = round(s["size"], 1)
        by_size[size] = by_size.get(size, 0) + len(s["text"])
    font_size = max(by_size.items(), key=lambda kv: kv[1])[0]

    x0, y0, x1, y1 = raw_line["bbox"]
    return Line(page_no, x0, y0, x1, y1, text, font_size, bold * 2 > total)


def _find_tables(page: pymupdf.Page, page_no: int) -> list[TableBox]:
    """至少 2 行 2 列的带边框表格。是不是真的表格（格子里有没有字）留给 layout 判断。"""
    try:
        found = page.find_tables().tables
    except Exception:  # noqa: BLE001 —— 表格识别失败不影响解析，按这一页没有表格处理
        logger.warning("第 %s 页表格识别失败，按没有表格处理", page_no, exc_info=True)
        return []
    return [
        TableBox(page_no, tuple(t.bbox), [[tuple(c) for c in row.cells if c] for row in t.rows])
        for t in found
        if t.row_count >= 2 and t.col_count >= 2
    ]


def extract_pdf(path: str | Path) -> ExtractResult:
    """抽取 PDF 的全部文字行。

    Raises:
        EncryptedPdfError: 文件已加密。
        ScannedPdfError: 全文可用字符数低于阈值，判定为扫描件。
    """
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise EncryptedPdfError(str(path))

        lines: list[Line] = []
        pages: list[PageInfo] = []
        tables: list[TableBox] = []
        for index, page in enumerate(doc):
            page_no = index + 1
            data = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
            image_count = len(page.get_images(full=True))
            pages.append(PageInfo(page_no, page.rect.width, page.rect.height, image_count))

            for block in data["blocks"]:
                if block["type"] != 0:  # 0 = 文本块
                    continue
                for raw_line in block["lines"]:
                    line = _line_from_spans(page_no, raw_line)
                    if line is not None:
                        lines.append(line)
            tables.extend(_find_tables(page, page_no))

    result = ExtractResult(
        lines=lines,
        pages=pages,
        ats_signals={"images": sum(p.image_count for p in pages), "textboxes": 0, "drawings": 0},
        tables=tables,
    )
    if result.char_count < settings.SCANNED_PDF_MIN_CHARS:
        raise ScannedPdfError(f"{path}: 仅抽出 {result.char_count} 个字符")
    return result
