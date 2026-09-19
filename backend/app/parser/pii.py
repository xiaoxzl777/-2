"""个人信息：本地抽取 + 外发前掩码（系统不变量⑤）。

- extract_basics：姓名 / 电话 / 邮箱 / 所在地 用正则和版面特征在本地抽取，basics 章节永不发给 LLM。
- mask_pii：发给 LLM 的其余文本先掩码。掩码**逐字符替换、长度不变**，
  所以在掩码文本上算出的 char 偏移与原文完全一致，证据定位不需要任何换算。

领域层：纯函数，不碰数据库，不调任何 API。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.parser.layout import Block, LayoutResult
from app.parser.section import Section

_PHONE = re.compile(r"(?<![\d.])(?:\+?86[- ]?)?1[3-9]\d[- ]?\d{4}[- ]?\d{4}(?![\d.])")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_ID_CARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_LOCATION = re.compile(r"(?:现居地?|所在地|居住地|现住址|住址|地址|籍贯)\s*[:：]\s*([一-鿿A-Za-z·]{2,15})")

_CJK_NAME = re.compile(r"^[一-鿿]{2,4}(?:·[一-鿿]{1,6})?$")
_LATIN_NAME = re.compile(r"^[A-Za-z][A-Za-z.'-]*(?: [A-Za-z][A-Za-z.'-]*){1,3}$")
# 会被误当成姓名的常见短词
_NOT_A_NAME = {"个人简历", "简历", "个人信息", "基本信息", "求职简历", "我的简历", "resume", "curriculum vitae", "cv"}

BASICS_SCAN_BLOCKS = 8  # 没识别出 basics 章节时，只在开头这几块里找


@dataclass(slots=True)
class Basics:
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _looks_like_name(text: str) -> bool:
    t = text.strip()
    if t.lower() in _NOT_A_NAME:
        return False
    return bool(_CJK_NAME.match(t) or _LATIN_NAME.match(t))


def _find_name(blocks: list[Block]) -> str | None:
    """姓名 = 开头区域里"长得像人名"的块中字号最大的那个；字号相同取最靠前的。"""
    candidates = [b for b in blocks if _looks_like_name(b.text)]
    if not candidates:
        return None
    best = max(candidates, key=lambda b: (b.font_size or 0, -b.block_index))
    return best.text.strip()


def extract_basics(layout: LayoutResult, sections: list[Section]) -> Basics:
    blocks = layout.blocks
    if sections and sections[0].type == "basics":
        head = blocks[sections[0].block_start: sections[0].block_end + 1]
    else:
        head = blocks[:BASICS_SCAN_BLOCKS]
    text = "\n".join(b.text for b in head)

    email = _EMAIL.search(text)
    phone = _PHONE.search(text)
    location = _LOCATION.search(text)
    return Basics(
        name=_find_name(head),
        email=email.group(0) if email else None,
        phone=re.sub(r"[- ]", "", phone.group(0)) if phone else None,
        location=location.group(1) if location else None,
    )


def _mask_digits(m: re.Match) -> str:
    return re.sub(r"[\dXx]", "X", m.group(0))


def _mask_email(m: re.Match) -> str:
    return re.sub(r"[^@.]", "*", m.group(0))


def mask_pii(text: str, name: str | None = None) -> str:
    """把电话、邮箱、身份证号、姓名替换成等长的占位字符。返回值与输入长度严格相等。"""
    masked = _ID_CARD.sub(_mask_digits, text)   # 先处理身份证：它包含一段会被电话正则命中的数字
    masked = _PHONE.sub(_mask_digits, masked)
    masked = _EMAIL.sub(_mask_email, masked)
    if name and len(name.strip()) >= 2:
        masked = masked.replace(name.strip(), "某" * len(name.strip()))
    assert len(masked) == len(text), "掩码必须保持长度不变，否则 char 偏移会错位"
    return masked
