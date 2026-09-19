"""匹配的确定性通道：能用规则判定的要求项不花钱、不调模型，结论百分之百可复现。

三个判定器各管一类要求，判不了就返回 None，留给后面的 RAG + LLM 通道：
  · 技能   要求项带 skill_id，且简历的 skill_mentions 里有同一个 skill_id
  · 学历   要求里写了学历层次（本科 / 硕士…），与简历的最高学历比
  · 年限   要求里写了"N 年"，与简历的工作 / 实习总时长比
评分同样是公式：每条要求按状态折算（hit 1 / partial 0.5 / miss 0），再按权重加权。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date

from app.parser.normalize import months_between

STATUS_VALUE = {"hit": 1.0, "partial": 0.5, "miss": 0.0}
CATEGORIES = ("skill", "education", "experience", "other")
_EXPERIENCE_SECTIONS = ("work", "projects")

_DEGREES = [(4, re.compile(r"博士|ph\.?d", re.I)), (3, re.compile(r"硕士|研究生|master", re.I)),
            (2, re.compile(r"本科|学士|bachelor", re.I)), (1, re.compile(r"大专|专科"))]
_DEGREE_NAMES = {4: "博士", 3: "硕士", 2: "本科", 1: "大专"}
_YEARS = re.compile(r"(\d{1,2})\s*年")


@dataclass(slots=True)
class MatchItem:
    requirement_id: int
    status: str                          # hit / partial / miss
    matched_by: str | None               # dict / profile / rag / fulltext；miss 且没人判过为 None
    reason: str
    evidence_quote: str | None = None    # 简历原文：full_text[char_start:char_end]
    char_start: int | None = None
    char_end: int | None = None
    unit_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def match_by_rules(requirement: dict, structure: dict, full_text: str, today: date | None = None) -> MatchItem | None:
    """按要求项的类别分派给对应的判定器。返回 None = 规则判不了。"""
    if requirement.get("skill_id"):
        return _match_skill(requirement, structure, full_text)
    if requirement["category"] == "education":
        return _match_education(requirement, structure, full_text)
    if requirement["category"] == "experience":
        return _match_years(requirement, structure, today or date.today())
    return None


def _match_skill(req: dict, structure: dict, full_text: str) -> MatchItem | None:
    mentions = [m for m in structure.get("skill_mentions", []) if m["skill_id"] == req["skill_id"]]
    if not mentions:
        return None                      # 词典没扫到不代表不会：可能换了说法，交给模型判断
    used = next((m for m in mentions if m["section_type"] in _EXPERIENCE_SECTIONS), None)
    best = used or mentions[0]
    span = _line_around(full_text, best["char_start"], best["char_end"])
    return MatchItem(
        requirement_id=req["id"], status="hit" if used else "partial", matched_by="dict",
        reason="在项目 / 工作经历中用到了这项技能" if used else "只出现在技能清单里，经历中没有体现实际使用",
        evidence_quote=full_text[span[0]:span[1]], char_start=span[0], char_end=span[1])


def _match_education(req: dict, structure: dict, full_text: str) -> MatchItem | None:
    required = degree_level(f"{req['content']} {req.get('quote', '')}")
    entries = [(degree_level(e.get("degree") or ""), e) for e in structure.get("education", [])]
    entries = [(level, e) for level, e in entries if level]
    if not required or not entries:
        return None
    level, entry = max(entries, key=lambda pair: pair[0])
    ok = level >= required
    return MatchItem(
        requirement_id=req["id"], status="hit" if ok else "miss", matched_by="profile",
        reason=f"最高学历为{_DEGREE_NAMES[level]}，{'满足' if ok else '低于'}要求的{_DEGREE_NAMES[required]}",
        evidence_quote=full_text[entry["char_start"]:entry["char_end"]],
        char_start=entry["char_start"], char_end=entry["char_end"])


def _match_years(req: dict, structure: dict, today: date) -> MatchItem | None:
    found = _YEARS.search(f"{req['content']} {req.get('quote', '')}")
    if not found:
        return None                      # "有高并发项目经验"这类没有年限的，规则判不了
    required = int(found.group(1))
    have = experience_years(structure, today)
    status = "hit" if have >= required else "partial" if have >= required / 2 else "miss"
    return MatchItem(requirement_id=req["id"], status=status, matched_by="profile",
                     reason=f"要求 {required} 年，简历中的工作与实习经历合计约 {have:.1f} 年")


def degree_level(text: str) -> int:
    """文字里出现的最高学历层次：博士 4 / 硕士 3 / 本科 2 / 大专 1；没有则 0。"""
    return next((level for level, pattern in _DEGREES if pattern.search(text)), 0)


def experience_years(structure: dict, today: date) -> float:
    """工作与实习经历的总时长（年）。重叠的区间合并后再求和；校园经历不算；日期不完整的跳过。"""
    now = f"{today.year:04d}-{today.month:02d}"
    spans = []
    for e in structure.get("work", []):
        end = now if e.get("is_present") else e.get("end")
        if e.get("kind") == "campus" or not e.get("start") or not end:
            continue
        if (months_between(e["start"], end) or 0) > 0:
            spans.append((e["start"], end))
    total, covered_until = 0, ""
    for start, end in sorted(spans):
        start = max(start, covered_until)
        if end > start:
            total += months_between(start, end)
            covered_until = end
    return round(total / 12, 1)


def _line_around(full_text: str, start: int, end: int, limit: int = 80) -> tuple[int, int]:
    """技能名所在的那一行（过长则截到 limit 字），作为展示给用户的证据。"""
    line_start = full_text.rfind("\n", 0, start) + 1
    line_end = full_text.find("\n", end)
    line_end = len(full_text) if line_end == -1 else line_end
    if line_end - line_start > limit:
        line_start = max(line_start, start - limit // 2)
        line_end = min(line_end, line_start + limit)
    return line_start, max(line_end, end)


def score_match(requirements: list[dict], items: list[MatchItem]) -> tuple[float | None, dict[str, float | None]]:
    """返回 (总匹配度, 各类别匹配度)，均为 0–100。某类别在 JD 里没有要求 → None，不参与展示。"""
    status = {i.requirement_id: i.status for i in items}

    def weighted(reqs: list[dict]) -> float | None:
        total = sum(r["weight"] for r in reqs)
        if not total:
            return None
        got = sum(r["weight"] * STATUS_VALUE[status.get(r["id"], "miss")] for r in reqs)
        return round(100 * got / total, 1)

    by_category = {c: weighted([r for r in requirements if r["category"] == c]) for c in CATEGORIES}
    return weighted(requirements), by_category
