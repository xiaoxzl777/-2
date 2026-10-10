"""匹配的确定性通道：能用规则判定的要求项不花钱、不调模型，结论百分之百可复现。

三个判定器各管一类要求，判不了就返回 None，留给后面的模型通道：
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

_DEGREES = [(4, re.compile(r"博士|ph\.?d", re.I)), (3, re.compile(r"硕士|(?<!博士)研究生|master", re.I)),   # "博士研究生"只算博士
            (2, re.compile(r"本科|学士|bachelor", re.I)), (1, re.compile(r"大专|专科"))]
_DEGREE_NAMES = {4: "博士", 3: "硕士", 2: "本科", 1: "大专"}
# "N 年"或"N-M 年"（取下限）。前面不能紧挨数字：不然"2026年毕业"会被读成"要求 26 年"
_YEARS = re.compile(r"(?<!\d)(\d{1,2})(?:\s*[-–—~～至到]\s*\d{1,2})?\s*年")
MAX_REQUIRED_YEARS = 15       # 再大多半不是在说工作年限，规则不判，交给模型
MAX_PLAIN_EXTRA = 6           # 要求去掉技能名后最多还剩几个字，才算"只是要求会这项技能"


@dataclass(slots=True)
class MatchItem:
    requirement_id: int
    status: str                          # hit / partial / miss
    matched_by: str | None               # dict / profile / fulltext；miss 且没人判过为 None
    reason: str
    evidence_quote: str | None = None    # 简历原文：full_text[char_start:char_end]
    char_start: int | None = None
    char_end: int | None = None
    unit_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def match_by_rules(requirement: dict, structure: dict, full_text: str, today: date | None = None, *,
                   strict: bool = True) -> MatchItem | None:
    """按要求项的类别分派给对应的判定器。返回 None = 规则判不了。

    strict（后面还有模型兜底时用）：技能类只在十拿九稳时下结论——要求就是技能名本身、且经历里确实用过。
    "熟悉 Redis 缓存穿透、击穿、雪崩的解决方案"这种带限定语的，光看到 Redis 字样不能算满足；
    "只列在技能清单里"也可能只是没写出字面（Spring Boot 项目当然用了 Java）——这些都留给模型判断。
    不 strict（dict_only 基线）：词典能判的全判，看看纯规则能做到什么程度。
    """
    if requirement.get("skill_id"):
        item = _match_skill(requirement, structure, full_text)
        if strict and item is not None and (item.status != "hit" or not _is_plain_skill_requirement(requirement)):
            return None
        return item
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


def recheck_listed_only(item: MatchItem, req: dict, structure: dict, full_text: str) -> MatchItem:
    """模型复核之后再用规则把一次关。hybrid 把"只写在技能栏"的技能也交给模型（技能栏里的 Java 可能就是 Spring Boot 项目里在用的），
    但模型常常看到"专业技能中列出了 X"就判满足，和提示词里"只是提到、没有实际使用 = 部分满足"相反（05 5.3 (2)(7)(8)）。
    所以：规则知道这项技能只出现在经历以外的地方、模型说满足、给的依据又不在任何一段项目 / 工作经历里 → 照规则记部分满足。
    依据落在经历里的（模型找到了没写字面的用法）照模型的。"""
    if item.status != "hit" or not req.get("skill_id") or item.char_start is None:
        return item
    rule = _match_skill(req, structure, full_text)
    if rule is None or rule.status != "partial" or _in_experience(structure, item.char_start, item.char_end):
        return item
    return rule


def _in_experience(structure: dict, start: int, end: int) -> bool:
    """区间和某段项目 / 工作经历有重叠。"""
    return any(e.get("char_start") is not None and e["char_start"] < end and start < e["char_end"]
               for key in _EXPERIENCE_SECTIONS for e in structure.get(key, []))


def _is_plain_skill_requirement(req: dict) -> bool:
    """要求是否只是"会某项技能"：去掉技能名后剩下的字很少（"熟悉 Redis" 剩 2 个字）。
    剩得多说明另有限定（"熟悉 Redis 缓存穿透、击穿、雪崩的解决方案"），光看到技能名不能算满足。"""
    rest = re.sub(re.escape(req.get("skill") or ""), "", req["content"], flags=re.I)
    return len("".join(rest.split())) <= MAX_PLAIN_EXTRA


def _match_education(req: dict, structure: dict, full_text: str) -> MatchItem | None:
    required = _required_degree(req)
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
    if not found or not 0 < int(found.group(1)) <= MAX_REQUIRED_YEARS:
        return None                      # "有高并发项目经验"这类没有年限的、"2026年毕业"这类年份，规则判不了
    required = int(found.group(1))
    have = experience_years(structure, today)
    status = "hit" if have >= required else "partial" if have >= required / 2 else "miss"
    return MatchItem(requirement_id=req["id"], status=status, matched_by="profile",
                     reason=f"要求 {required} 年，简历中的工作与实习经历合计约 {have:.1f} 年")


def degree_level(text: str) -> int:
    """文字里出现的最高学历层次：博士 4 / 硕士 3 / 本科 2 / 大专 1；没有则 0。"""
    return max(_degree_levels(text), default=0)


def _degree_levels(text: str) -> list[int]:
    return [level for level, pattern in _DEGREES if pattern.search(text)]


def _required_degree(req: dict) -> int:
    """要求的学历门槛 = 要求里提到的最低一档："本科或硕士在读"的门槛是本科，不是硕士。
    先只看模型复述的 content；JD 原话（quote）里常带"硕士优先"这类加分项，content 里没写学历时才看它。"""
    for text in (req["content"], req.get("quote") or ""):
        levels = _degree_levels(text)
        if levels:
            return min(levels)
    return 0


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
