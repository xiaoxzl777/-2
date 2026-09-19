"""证据溯源：模型说"原文里有这句话"，这里负责核实它到底在不在、在哪。

这是反幻觉机制的核心（系统不变量⑥）：诊断 finding、JD 匹配依据、面试评分依据，
凡是模型引用的原文都要过这一关；定位不到的一律丢弃。全系统只有这一个定位函数。

定位顺序：先在 hint 区间（通常是送审的那条经历）里找，找不到再扩大到全文；
每一轮都是 先精确匹配 → 再模糊匹配（RapidFuzz 对齐，得分 ≥ 阈值）。

匹配前对两边做归一化（全角标点→半角、换行→空格、英文转小写）。归一化是**逐字符、长度不变**的，
所以在归一化文本上得到的位置可以直接用在原文上——模型把"，"写成","、把跨行的句子接成一行，
都属于格式差异，不算幻觉。

领域层：纯函数，不碰数据库，不调任何 API。
"""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from app.config import settings

MIN_QUOTE_LEN = 2         # 比这更短的引用没有证据价值
MIN_FUZZY_LEN = 6         # 太短的引用做模糊匹配没有意义（随便一段文字都能"差不多像"）

# 一对一的字符映射：全角 ASCII（！到～）、中文标点、各种空白
_CHAR_MAP = {code: code - 0xFEE0 for code in range(0xFF01, 0xFF5F)}
_CHAR_MAP.update({ord(k): ord(v) for k, v in {
    "　": " ", "\n": " ", "\t": " ", "\r": " ", " ": " ",
    "。": ".", "、": ",", "“": '"', "”": '"', "‘": "'", "’": "'",
    "【": "[", "】": "]", "《": "<", "》": ">", "—": "-", "–": "-", "～": "~", "·": ".",
}.items()})
# 大写 → 小写只处理 ASCII（含全角 Ａ–Ｚ），保证长度不变。translate 只走一遍，所以全角大写要直接映射到半角小写
for _upper in range(ord("A"), ord("Z") + 1):
    _CHAR_MAP[_upper] = _upper + 32
    _CHAR_MAP[_upper + 0xFEE0] = _upper + 32

_QUOTE_WRAPPERS = " \t\r\n\"'“”‘’「」『』…."


@dataclass(slots=True, frozen=True)
class Span:
    start: int
    end: int          # 开区间，相对传入的 text
    score: float      # 1.0 = 精确匹配；模糊匹配为 0–1
    method: str       # exact / fuzzy


def normalize_for_match(s: str) -> str:
    out = s.translate(_CHAR_MAP)
    assert len(out) == len(s), "归一化必须保持长度不变"
    return out


def _search(quote: str, text: str, lo: int, hi: int) -> Span | None:
    window = text[lo:hi]
    at = window.find(quote)
    if at >= 0:
        return Span(lo + at, lo + at + len(quote), 1.0, "exact")
    if len(quote) < MIN_FUZZY_LEN or len(quote) > len(window):
        return None
    hit = fuzz.partial_ratio_alignment(quote, window)  # 在 window 里找与 quote 最像的一段
    if hit is None or hit.score < settings.EVIDENCE_FUZZY_MIN:
        return None
    return Span(lo + hit.dest_start, lo + hit.dest_end, round(hit.score / 100, 3), "fuzzy")


def locate_span(quote: str, text: str, hint: tuple[int, int] | None = None) -> Span | None:
    """在 text 中定位 quote。找不到返回 None——调用方应把它当作幻觉处理。"""
    needle = normalize_for_match(quote.strip(_QUOTE_WRAPPERS))
    if len(needle) < MIN_QUOTE_LEN:
        return None
    haystack = normalize_for_match(text)

    if hint is not None:
        lo, hi = max(0, hint[0]), min(len(text), hint[1])
        found = _search(needle, haystack, lo, hi)
        if found:
            return found
    return _search(needle, haystack, 0, len(text))
