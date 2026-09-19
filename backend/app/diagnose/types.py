"""诊断里两条通道（规则 / LLM）共用的数据类型。"""
from __future__ import annotations

from dataclasses import asdict, dataclass

CATEGORIES = ("completeness", "quantification", "expression", "consistency", "ats")


@dataclass(slots=True, frozen=True)
class ReviewUnit:
    """一个送审单元：一条经历描述，或整段自我评价。诊断以它为粒度。"""

    unit_id: str          # 如 projects[0].highlights[2]、summary
    unit_type: str        # work / projects / summary
    entry_name: str | None
    char_start: int
    char_end: int
    text: str             # full_text[char_start:char_end]，逐字原文


@dataclass(slots=True)
class Finding:
    """一个被发现的问题。字段与 findings 表一一对应。"""

    source: str                       # rule / llm
    category: str                     # CATEGORIES 之一，决定计入哪个评分维度
    severity: str                     # high / medium / low
    title: str
    description: str
    suggestion: str
    rule_code: str | None = None      # 规则通道
    risk_type: str | None = None      # LLM 通道
    unit_id: str | None = None
    evidence_quote: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    verify_result: str = "exact"      # 规则的证据取自原文切片，恒为 exact
    match_score: float | None = 1.0
    attempt_no: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


def iter_units(structure: dict, full_text: str) -> list[ReviewUnit]:
    """从结构化结果里取出全部送审单元。条目没有拆出 highlight 时，整个条目作为一个单元。"""
    units: list[ReviewUnit] = []

    def add(unit_id: str, unit_type: str, name: str | None, span: dict) -> None:
        start, end = span["char_start"], span["char_end"]
        units.append(ReviewUnit(unit_id, unit_type, name, start, end, full_text[start:end]))

    for key in ("work", "projects"):
        for i, entry in enumerate(structure.get(key) or []):
            highlights = entry.get("highlights") or []
            for j, h in enumerate(highlights):
                add(f"{key}[{i}].highlights[{j}]", key, entry.get("name"), h)
            if not highlights:
                add(f"{key}[{i}]", key, entry.get("name"), entry)
    if structure.get("summary"):
        add("summary", "summary", None, structure["summary"])
    return units
