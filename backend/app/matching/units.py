"""匹配用的检索单元：简历里每一段"可以拿来证明某项要求"的文字。

比诊断的送审单元（diagnose.types.iter_units）范围更大，要覆盖简历里一切可能成为依据的内容：
  · 每条经历描述、自我评价（与诊断相同）
  · 每段经历的"头部"：名称、角色、技术栈、项目描述——"熟悉 Spring Boot"的依据常常就是那行"技术栈：…"
  · 教育经历、技能章节的每一行、每个奖项 / 证书
漏掉任何一类，RAG 通道就会把明明写在简历上的东西判成 miss。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.diagnose.types import ReviewUnit, iter_units

MIN_LINE_LEN = 4          # 技能章节里比这更短的行不作为单元
MAX_GROUP_TITLE_LEN = 12  # "1.Java生态：" 这类分组小标题的最大长度（不含编号）
_LIST_PREFIX = re.compile(r"^(?:\d{1,2}[.、)）]|[•·▪■◆●*\-–—])?\s*")


@dataclass(slots=True, frozen=True)
class Candidate:
    """检索出来、准备交给模型判定的一个简历单元。"""

    unit_id: str
    unit_type: str
    entry_name: str | None
    char_start: int
    char_end: int
    text: str             # 掩码后的文本，用于放进 prompt
    score: float          # 精排相关度；未精排时为余弦相似度


def build_match_units(structure: dict, sections: list[dict], full_text: str) -> list[ReviewUnit]:
    units = iter_units(structure, full_text)
    units += _entry_head_units(structure, full_text)
    for i, edu in enumerate(structure.get("education") or []):
        start, end = edu["char_start"], edu["char_end"]
        units.append(ReviewUnit(f"education[{i}]", "education", None, start, end, full_text[start:end]))
    for section in (s for s in sections if s["type"] == "skills"):
        units += _skill_line_units(section, full_text)
    for i, award in enumerate(structure.get("awards") or []):
        start, end = award["char_start"], award["char_end"]
        units.append(ReviewUnit(f"awards[{i}]", "awards", None, start, end, full_text[start:end]))
    return units


def _entry_head_units(structure: dict, full_text: str) -> list[ReviewUnit]:
    """每段经历里排在第一条描述之前的部分。没有拆出描述的条目已经整段作为单元了，不再重复。"""
    units: list[ReviewUnit] = []
    for key in ("work", "projects"):
        for i, entry in enumerate(structure.get(key) or []):
            highlights = entry.get("highlights") or []
            if not highlights:
                continue
            start, end = entry["char_start"], min(h["char_start"] for h in highlights)
            head = full_text[start:end].rstrip()
            if len(head) >= MIN_LINE_LEN:
                units.append(ReviewUnit(f"{key}[{i}].head", key, entry.get("name"), start, start + len(head), head))
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
