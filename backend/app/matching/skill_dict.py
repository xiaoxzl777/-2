"""技能词典：在简历正文里标出"第几个字到第几个字提到了哪个技能"。

全系统只有这一个"文本 → skill_id"的入口；诊断规则（技能栏写了但项目里没提）、
JD 匹配的词典路、面试出题都查这份索引，不各自去正文里找。

词典是扁平的：只回答"这个词是不是某技能的另一种写法"（SpringBoot = Spring Boot）。
技能之间的上下位关系不建树，交给 LLM 判定。

匹配细节：
- 所有写法按长度降序编进一条正则，保证"微服务架构"先于"微服务"、"C++"先于"C"被匹配。
- 英文写法两侧不能紧挨字母数字（"Go" 不会命中 "Google"、"Java" 不会命中 "JavaScript"）。
- 两个字符以内的英文写法（C、Go、JS…）区分大小写，其余不区分。

领域层：纯函数，不碰数据库。词典由 service 层从 skills 表读出后传入。
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

SHORT_WORD_LEN = 2
_EXPERIENCE_SECTIONS = {"work", "projects"}


@dataclass(slots=True, frozen=True)
class SkillEntry:
    id: int
    canonical_name: str
    aliases: tuple[str, ...] = ()


def _is_ascii_word_char(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def _pattern(word: str) -> str:
    left = r"(?<![A-Za-z0-9])" if _is_ascii_word_char(word[0]) else ""
    right = r"(?![A-Za-z0-9])" if _is_ascii_word_char(word[-1]) else ""
    return left + re.escape(word) + right


def _compile(words: list[str], flags: int) -> re.Pattern | None:
    if not words:
        return None
    ordered = sorted(set(words), key=lambda w: (-len(w), w))
    return re.compile("|".join(_pattern(w) for w in ordered), flags)


class SkillDict:
    def __init__(self, entries: Iterable[SkillEntry]):
        self._by_exact: dict[str, int] = {}      # 短英文写法，区分大小写
        self._by_folded: dict[str, int] = {}     # 其余写法，小写后查
        self.names: dict[int, str] = {}
        for e in entries:
            self.names[e.id] = e.canonical_name
            for word in (e.canonical_name, *e.aliases):
                word = word.strip()
                if not word:
                    continue
                if word.isascii() and len(word) <= SHORT_WORD_LEN:
                    self._by_exact.setdefault(word, e.id)
                else:
                    self._by_folded.setdefault(word.lower(), e.id)
        self._exact_re = _compile(list(self._by_exact), 0)
        self._folded_re = _compile(list(self._by_folded), re.IGNORECASE)

    def __len__(self) -> int:
        return len(self.names)

    def lookup(self, word: str) -> int | None:
        """整个词是不是某个技能的写法。"""
        word = word.strip()
        return self._by_exact.get(word) or self._by_folded.get(word.lower())

    def find(self, text: str) -> list[tuple[int, int, int]]:
        """返回 [(skill_id, start, end)]，按位置排序、互不重叠（重叠时取更长的写法）。"""
        hits: list[tuple[int, int, int]] = []
        if self._folded_re:
            hits += [(self._by_folded[m.group(0).lower()], m.start(), m.end()) for m in self._folded_re.finditer(text)]
        if self._exact_re:
            hits += [(self._by_exact[m.group(0)], m.start(), m.end()) for m in self._exact_re.finditer(text)]

        hits.sort(key=lambda h: (h[1], -(h[2] - h[1])))
        result: list[tuple[int, int, int]] = []
        for hit in hits:
            if not result or hit[1] >= result[-1][2]:
                result.append(hit)
        return result


def _section_type_at(sections: list[dict], pos: int) -> str:
    for s in sections:
        if s["char_start"] <= pos < s["char_end"]:
            return s["type"]
    return "other"


def annotate_skills(structure: dict, full_text: str, sections: list[dict], skills: SkillDict) -> dict:
    """填好 structure 里与技能有关的三处：skill_mentions、skills[].skill_id、tech_stack[].skill_id。"""
    structure["skill_mentions"] = [
        {"skill_id": skill_id, "surface": full_text[start:end], "char_start": start, "char_end": end,
         "section_type": _section_type_at(sections, start), "matched_by": "dict"}
        for skill_id, start, end in skills.find(full_text)
    ]
    for item in structure.get("skills", []):
        item["skill_id"] = skills.lookup(item["name"])
    for entry in structure.get("work", []) + structure.get("projects", []):
        for tech in entry.get("tech_stack", []):
            tech["skill_id"] = skills.lookup(tech["name"])
    return structure


def mentioned_in_experience(structure: dict) -> set[int]:
    """在工作 / 项目经历正文里出现过的技能。"""
    return {m["skill_id"] for m in structure.get("skill_mentions", []) if m["section_type"] in _EXPERIENCE_SECTIONS}
