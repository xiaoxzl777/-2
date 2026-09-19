"""匹配用的检索单元：简历里每一段"可以拿来证明某项要求"的文字。

比诊断的送审单元（diagnose.types.iter_units）范围更大：除了每条经历描述与自我评价，
还包括技能章节的每一行、每个奖项 / 证书——"熟悉 JVM 内存模型""英语 CET-6"这类要求的依据往往在那里。
"""
from __future__ import annotations

import re

from app.diagnose.types import ReviewUnit, iter_units

MIN_LINE_LEN = 4          # 技能章节里比这更短的行不作为单元
MAX_GROUP_TITLE_LEN = 12  # "1.Java生态：" 这类分组小标题的最大长度（不含编号）
_LIST_PREFIX = re.compile(r"^(?:\d{1,2}[.、)）]|[•·▪■◆●*\-–—])?\s*")


def build_match_units(structure: dict, sections: list[dict], full_text: str) -> list[ReviewUnit]:
    units = iter_units(structure, full_text)
    for section in (s for s in sections if s["type"] == "skills"):
        units += _skill_line_units(section, full_text)
    for i, award in enumerate(structure.get("awards") or []):
        start, end = award["char_start"], award["char_end"]
        units.append(ReviewUnit(f"awards[{i}]", "awards", None, start, end, full_text[start:end]))
    return units


def _skill_line_units(section: dict, full_text: str) -> list[ReviewUnit]:
    """技能章节逐行成单元。分组小标题（"2.Python生态："）本身不含证据，不作为单元，
    而是作为它下面各行的 entry_name——和项目名一样，给检索补上下文。"""
    units: list[ReviewUnit] = []
    title = (section.get("title") or "").strip()
    group: str | None = None
    offset = section["char_start"]
    for n, line in enumerate(full_text[section["char_start"]:section["char_end"]].split("\n")):
        body = line.strip()
        label = _LIST_PREFIX.sub("", body)
        if label[-1:] in ("：", ":") and len(label) <= MAX_GROUP_TITLE_LEN + 1:
            group = label[:-1].strip() or None
        elif len(body) >= MIN_LINE_LEN and body != title:
            start = offset + line.index(body)
            units.append(ReviewUnit(f"skills.line[{n}]", "skills", group, start, start + len(body), body))
        offset += len(line) + 1
    return units
