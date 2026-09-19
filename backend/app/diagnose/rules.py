"""规则通道：7 条确定性规则。纯函数、不调任何 API、毫秒级、零幻觉、结果可复现。

每条规则是一个用 @rule 注册的函数：输入 RuleContext，产出若干 Finding。
新增规则 = 新写一个函数并注册，不需要改动别处。

规则的证据一律取自 full_text 的切片，所以 verify_result 恒为 exact，不需要再过 locate_span。
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date

from app.diagnose.types import Finding, ReviewUnit, iter_units
from app.matching.skill_dict import mentioned_in_experience
from app.parser.normalize import months_between

MAX_HIGHLIGHT_LEN = 120
MIN_HIGHLIGHT_LEN = 8
MAX_PAGES = 2
MAX_GAP_MONTHS = 3
MAX_SKILL_FINDINGS = 5        # 技能不一致最多报这么多条，避免刷屏

# 数字：前面不能紧挨字母 / 数字 / . # + -（排除 Vue3、JDK8、CET-6、2.7 这类名称与版本号）
_NUMBER = re.compile(r"(?<![A-Za-z\d.#+\-])\d+(?:\.\d+)?")
# 只收"结果性"的动词。不收"性能 / 效率"这类名词：否则小标题「性能优化：」本身就会被当成在陈述结果
_RESULT_WORDS = re.compile(r"提升|提高|降低|减少|缩短|节省|节约|增长|达到|降至|升至|支撑|保障|上线|获得|解决了|避免|稳定运行")
_WEAK_VERBS = re.compile(r"参与|协助|了解|学习|接触|帮助|配合|跟随|辅助")
# 行首的列表符号 / 编号。"10.5%" 这种小数不是编号，所以编号的点后面不能紧跟数字
_LINE_PREFIX = re.compile(r"^(?:[•·▪■◆●○◦*➢➤►▶✓☑\-–—]|\d{1,2}[.、)）](?!\d)|[（(]\d{1,2}[)）]|[①-⑩])?\s*")
_CLAUSE_END = re.compile(r"[，。；;,\n]")


@dataclass(slots=True)
class RuleContext:
    structure: dict
    full_text: str
    ats_signals: dict = field(default_factory=dict)
    page_count: int | None = None
    today: date = field(default_factory=date.today)
    units: list[ReviewUnit] = field(init=False)

    def __post_init__(self) -> None:
        self.units = iter_units(self.structure, self.full_text)

    @property
    def experience_units(self) -> list[ReviewUnit]:
        return [u for u in self.units if u.unit_type in ("work", "projects")]


Rule = Callable[[RuleContext], Iterable[Finding]]
RULES: dict[str, Rule] = {}


def rule(code: str) -> Callable[[Rule], Rule]:
    def register(fn: Rule) -> Rule:
        RULES[code] = fn
        return fn
    return register


def run_rules(ctx: RuleContext) -> list[Finding]:
    return [finding for fn in RULES.values() for finding in fn(ctx)]


# ───────────────────────── 取证据的小工具 ─────────────────────────


def _has_number(text: str) -> bool:
    """有没有量化数字。行首的列表编号（"1." "（2）"）不算。"""
    return any(_NUMBER.search(line, _LINE_PREFIX.match(line).end()) for line in text.split("\n"))


def _clause_around(unit: ReviewUnit, pos: int) -> tuple[int, int]:
    """unit.text 里包含位置 pos 的那个分句，返回在 full_text 中的区间。"""
    text = unit.text
    left = max((m.end() for m in _CLAUSE_END.finditer(text, 0, pos)), default=0)
    right_match = _CLAUSE_END.search(text, pos)
    right = right_match.start() if right_match else len(text)
    while left < right and text[left] == " ":
        left += 1
    return unit.char_start + left, unit.char_start + right


def _first_sentence(unit: ReviewUnit, limit: int = 60) -> tuple[int, int]:
    """单元的最后一行的第一句（小标题 + 正文的单元，正文在最后一行），不含行首的列表编号。"""
    text = unit.text
    line_start = text.rfind("\n") + 1
    line_start += _LINE_PREFIX.match(text[line_start:]).end()
    end_match = re.search(r"[。；;\n]", text[line_start:])
    end = line_start + (end_match.start() if end_match else len(text) - line_start)
    return unit.char_start + line_start, unit.char_start + min(end, line_start + limit)


def _finding(ctx: RuleContext, code: str, category: str, severity: str, title: str, description: str,
             suggestion: str, unit: ReviewUnit | None = None, span: tuple[int, int] | None = None) -> Finding:
    quote = ctx.full_text[span[0]:span[1]] if span else None
    return Finding(source="rule", rule_code=code, category=category, severity=severity, title=title,
                   description=description, suggestion=suggestion, unit_id=unit.unit_id if unit else None,
                   evidence_quote=quote, char_start=span[0] if span else None, char_end=span[1] if span else None)


# ───────────────────────── 七条规则 ─────────────────────────


@rule("NO_QUANTIFICATION")
def no_quantification(ctx: RuleContext) -> Iterable[Finding]:
    """说了"提升 / 降低"却没有任何数字。"""
    for u in ctx.experience_units:
        result = _RESULT_WORDS.search(u.text)
        if result and not _has_number(u.text):
            yield _finding(ctx, "NO_QUANTIFICATION", "quantification", "high", "成果缺少量化数据",
                           f"这条描述提到了「{result.group(0)}」，但没有给出任何数字，读者无法判断成果的大小。",
                           "补充可验证的数字：优化前后的指标、数据规模、用户量、耗时等。没有真实数据就删掉这句空话。",
                           u, _clause_around(u, result.start()))


@rule("STAR_INCOMPLETE")
def star_incomplete(ctx: RuleContext) -> Iterable[Finding]:
    """只写了做了什么，没有写结果。"""
    for u in ctx.experience_units:
        if not _RESULT_WORDS.search(u.text) and not _has_number(u.text):
            yield _finding(ctx, "STAR_INCOMPLETE", "completeness", "medium", "只有做了什么，没有结果",
                           "这条描述停留在「做了某事」，没有说明带来了什么结果（STAR 中的 R）。",
                           "补一句结果：解决了什么问题、达到了什么效果、支撑了什么业务。",
                           u, _first_sentence(u))


@rule("WEAK_VERB")
def weak_verb(ctx: RuleContext) -> Iterable[Finding]:
    """以"参与 / 协助 / 了解"开头，看不出本人的贡献。"""
    for u in ctx.experience_units:
        offset = 0
        for line in u.text.split("\n"):
            body_at = _LINE_PREFIX.match(line).end()
            verb = _WEAK_VERBS.match(line, body_at)
            if verb:
                start = u.char_start + offset + verb.start()
                yield _finding(ctx, "WEAK_VERB", "expression", "low", f"以弱动词「{verb.group(0)}」开头",
                               f"「{verb.group(0)}」说明不了你具体做了什么、承担了多大责任。",
                               "换成能体现个人贡献的动词：设计、实现、主导、优化、重构、排查、搭建。",
                               u, (start, _clause_around(u, offset + verb.start())[1]))
                break  # 每个单元只报一次
            offset += len(line) + 1


@rule("SKILL_PROJECT_MISMATCH")
def skill_project_mismatch(ctx: RuleContext) -> Iterable[Finding]:
    """技能栏写了，但工作 / 项目经历里从未出现——面试时最容易被追问的地方。"""
    entries = (ctx.structure.get("work") or []) + (ctx.structure.get("projects") or [])
    if not entries:
        return
    used_ids = mentioned_in_experience(ctx.structure)
    experience_text = "\n".join(ctx.full_text[e["char_start"]:e["char_end"]] for e in entries).lower()

    reported = 0
    for skill in ctx.structure.get("skills") or []:
        if reported >= MAX_SKILL_FINDINGS:
            break
        skill_id, name = skill.get("skill_id"), skill["name"]
        # 词典认识的技能按 skill_id 比（写法不同也算出现过）；不认识的退回字面查找
        used = skill_id in used_ids if skill_id else name.lower() in experience_text
        if not used:
            reported += 1
            yield _finding(ctx, "SKILL_PROJECT_MISMATCH", "consistency", "medium", f"技能「{name}」在经历中没有体现",
                           f"技能栏列出了「{name}」，但所有工作 / 项目经历的描述里都没有提到它。",
                           "在用到它的经历里写明怎么用的；如果确实没用过，建议从技能栏移除或降低熟练度描述。",
                           None, (skill["char_start"], skill["char_end"]))


@rule("TIMELINE_ANOMALY")
def timeline_anomaly(ctx: RuleContext) -> Iterable[Finding]:
    """工作 / 实习经历之间时间重叠，或空窗超过 3 个月。校园经历天然与实习重叠，不参与。"""
    this_month = f"{ctx.today.year:04d}-{ctx.today.month:02d}"
    spans = []
    for i, e in enumerate(ctx.structure.get("work") or []):
        start = e.get("start")
        end = this_month if e.get("is_present") else e.get("end")
        # 只有年份精度的无法判断"是否超过 3 个月"，跳过
        if e.get("kind") in ("work", "internship") and start and end and len(start) == 7 and len(end) == 7:
            spans.append((start, end, i, e))
    spans.sort(key=lambda s: s[0])

    for (_, prev_end, _, prev), (start, _, i, entry) in zip(spans, spans[1:]):
        gap = months_between(prev_end, start)
        first_line_end = ctx.full_text.find("\n", entry["char_start"], entry["char_end"])
        span = (entry["char_start"], first_line_end if first_line_end > 0 else entry["char_end"])
        names = f"「{prev.get('name') or '上一段经历'}」与「{entry.get('name') or '这段经历'}」"
        if gap < 0:
            yield _finding(ctx, "TIMELINE_ANOMALY", "consistency", "medium", "经历时间重叠",
                           f"{names}的时间有 {-gap} 个月重叠。", "核对起止时间；如确为同时进行，请在描述中说明（如兼职、远程）。",
                           None, span)
        elif gap > MAX_GAP_MONTHS:
            yield _finding(ctx, "TIMELINE_ANOMALY", "consistency", "medium", f"经历之间有 {gap} 个月空窗",
                           f"{names}之间间隔 {gap} 个月，面试官通常会问这段时间在做什么。",
                           "如果这段时间在备考、做项目或学习，可以在简历中简要说明。", None, span)


@rule("ATS_UNFRIENDLY")
def ats_unfriendly(ctx: RuleContext) -> Iterable[Finding]:
    """含图片 / 文本框 / 绘图对象，企业的简历筛选系统（ATS）可能读不出来。"""
    labels = {"images": "图片", "textboxes": "文本框", "drawings": "绘图对象"}
    present = [f"{labels[k]} {v} 个" for k, v in ctx.ats_signals.items() if k in labels and v]
    if present:
        yield _finding(ctx, "ATS_UNFRIENDLY", "ats", "low", "含有机器不易解析的元素",
                       f"简历中包含{'、'.join(present)}。很多企业用系统自动解析简历，这些元素里的内容会被忽略。",
                       "关键信息（联系方式、技能、经历）务必以普通文字呈现；照片可保留，但不要把文字做成图片。")


@rule("LENGTH_ANOMALY")
def length_anomaly(ctx: RuleContext) -> Iterable[Finding]:
    """单条描述过长 / 过短，或整份简历超过 2 页。"""
    for u in ctx.experience_units:
        body = u.text[u.text.rfind("\n") + 1:]
        if len(body) > MAX_HIGHLIGHT_LEN:
            yield _finding(ctx, "LENGTH_ANOMALY", "expression", "low", f"单条描述过长（{len(body)} 字）",
                           f"一条描述超过 {MAX_HIGHLIGHT_LEN} 字，重点容易被淹没。",
                           "拆成 2–3 条，每条只讲一件事：做了什么、怎么做的、结果如何。", u, _first_sentence(u))
        elif len(body) < MIN_HIGHLIGHT_LEN:
            yield _finding(ctx, "LENGTH_ANOMALY", "expression", "low", "单条描述过短",
                           "这条描述信息量太少。", "补充具体做法与结果，或并入相邻的描述。",
                           u, (u.char_start, u.char_end))
    if ctx.page_count and ctx.page_count > MAX_PAGES:
        yield _finding(ctx, "LENGTH_ANOMALY", "expression", "low", f"简历共 {ctx.page_count} 页",
                       f"应届生简历建议控制在 1 页，最多 {MAX_PAGES} 页。", "删去与目标岗位无关的经历，压缩重复的描述。")
