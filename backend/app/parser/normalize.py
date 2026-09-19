"""时间归一化：把简历里五花八门的起止时间写法统一成 "YYYY-MM" / "YYYY"。

支持：2023.09 / 2023.9 / 2023-09 / 2023/9 / 2023年9月 / Sep 2023 / September 2023 / 仅年份 2023
连接符：- – — ~ ～ 至 到 to；结束为 至今 / 现在 / 目前 / Present / Now / Current 时 is_present=True。

两条规则：
- 先按"起 连接符 止"整体匹配，失败再退回单个日期。
- 两端精度不一致（如 2023.9-2024）时统一取粗的一端——宁可少一点信息，也不要编造月份。
  只有年份精度的区间无法判断"空窗是否超过 3 个月"，规则引擎见到会直接跳过。

领域层：纯函数，不碰数据库，不调任何 API。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

_YEAR = r"(?:19|20)\d{2}"
_PRESENT = r"(?P<present>至今|现在|目前|今|present|now|current)"
_SEP = r"\s*(?:-|–|—|~|～|至|到|\bto\b)+\s*"


def _date(n: int) -> str:
    """第 n 个日期的正则。三种写法的捕获组名都带上 n，起止两个日期才能出现在同一个正则里。"""
    # 月份后面不能再跟数字：否则 "2021-2023" 会被读成 "2021 年 20 月"
    year_month = rf"(?P<y{n}>{_YEAR})\s*[.\-/年]\s*(?P<m{n}>1[0-2]|0?[1-9])(?!\d)\s*月?"
    month_year = (rf"(?P<mon{n}>jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?"
                  rf"\s*,?\s*(?P<ey{n}>{_YEAR})")
    year_only = rf"(?P<yo{n}>{_YEAR})\s*年?"
    return f"(?:{year_month}|{month_year}|{year_only})"


_RANGE = re.compile(rf"(?<!\d){_date(1)}{_SEP}(?:{_date(2)}|{_PRESENT})(?!\d)", re.I)
_SINGLE = re.compile(rf"(?<!\d){_date(1)}(?!\d)", re.I)


@dataclass(slots=True, frozen=True)
class DateRange:
    start: str | None       # "YYYY-MM" 或 "YYYY"
    end: str | None         # 单个日期或"至今"时为 None
    is_present: bool
    span: tuple[int, int]   # 在输入文本中的位置，开区间

    @property
    def month_precision(self) -> bool:
        return bool(self.start and len(self.start) == 7)


def _read(m: re.Match, n: int) -> tuple[int, int | None] | None:
    """取出第 n 个日期的 (年, 月)；月份缺失为 None。"""
    g = m.groupdict()
    if g.get(f"y{n}"):
        return int(g[f"y{n}"]), int(g[f"m{n}"])
    if g.get(f"ey{n}"):
        return int(g[f"ey{n}"]), _MONTHS[g[f"mon{n}"].lower()[:3]]
    if g.get(f"yo{n}"):
        return int(g[f"yo{n}"]), None
    return None


def _fmt(date: tuple[int, int | None], with_month: bool) -> str:
    year, month = date
    return f"{year:04d}-{month:02d}" if with_month and month else f"{year:04d}"


def find_date_range(text: str) -> DateRange | None:
    """返回文本中第一个起止时间（或单个日期）；找不到返回 None。"""
    m = _RANGE.search(text)
    if m:
        start, end = _read(m, 1), _read(m, 2)
        with_month = start[1] is not None and (end is None or end[1] is not None)
        return DateRange(_fmt(start, with_month), _fmt(end, with_month) if end else None,
                         is_present=end is None, span=m.span())
    for m in _SINGLE.finditer(text):
        start = _read(m, 1)
        # 孤零零的四位数太容易是别的东西（"支撑 2000 名用户"）：必须带"年"字，或整段就只有它
        bare_year = start[1] is None and "年" not in m.group(0)
        if bare_year and m.group(0).strip() != text.strip():
            continue
        return DateRange(_fmt(start, True), None, is_present=False, span=m.span())
    return None


def months_between(earlier: str, later: str) -> int | None:
    """两个 "YYYY-MM" 之间相差的月数；任一端只有年份精度时无法计算，返回 None。"""
    if len(earlier) != 7 or len(later) != 7:
        return None
    (y1, m1), (y2, m2) = (map(int, s.split("-")) for s in (earlier, later))
    return (y2 - y1) * 12 + (m2 - m1)
