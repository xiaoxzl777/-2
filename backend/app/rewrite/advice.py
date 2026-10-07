"""具体建议：结果页上点开一条问题 / 差距时，现场让模型针对这一句、这条要求写建议。

用户嫌规则的固定模板"说得太泛"，所以每条都交给模型针对原文来写。两类建议都是带【段标题】的纯文本
（不用 JSON——要边生成边显示）：
    简历问题   【问题】【改成】【为什么】
    岗位差距   【考察什么】【怎么补】【面试怎么答】

反幻觉：【改成】/【怎么补】里出现原文没有的数字，一律换成【数值】（docs/04-design 5.8 的占位符复检）。
流式输出已经显示出去的字撤不回来，所以以复检后的全文为准存库，并在结束事件里下发给前端整段替换。

这里只做纯计算：拼 prompt 要的上下文、生成后复检。调模型与落库在 services/advice_service.py。
领域层：不碰数据库，不调任何 API。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.diagnose.rules import NUMBER    # 与规则引擎判断"有没有数字"同一口径（排除 Vue3、CET-6 这类名称与版本号）
from app.domains import DEFAULT, Domain, fill
from app.llm import prompts

PLACEHOLDER = "【数值】"
REQ_TYPE_LABEL = {"hard": "必须项", "plus": "加分项", "soft": "软素质"}
_ENTRY_KIND = {"projects": "项目", "work": "经历"}

_UNIT = re.compile(r"(work|projects)\[(\d+)\](?:\.highlights\[(\d+)\])?")
_SECTION = re.compile(r"【(问题|改成|为什么|考察什么|怎么补|面试怎么答)】")
_BRACKETED = re.compile(r"(【[^【】]*】)")


@dataclass(slots=True, frozen=True)
class AdvicePrompt:
    messages: list[tuple[str, str]]
    original: str          # 允许出现的数字以它为准（这段经历 / 简历全文的原文，未掩码）
    checked_section: str   # 要做数字复检的那一段


def _slice(text: str, start: int | None, end: int | None) -> str:
    return text[start:end] if start is not None and end is not None else ""


def _line_at(text: str, pos: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return start, len(text) if end < 0 else end


def finding_prompt(finding: dict, structure: dict, full_text: str, masked_text: str,
                   job_title: str | None, *, domain: Domain = DEFAULT) -> AdvicePrompt:
    """finding：findings 表的一行（unit_id、char 区间、title、description、evidence_quote）。
    发给模型的一律是掩码文本；定位不到所属条目（技能栏、整份简历的问题）时，经历部分给全部工作 / 项目经历。"""
    m = _UNIT.fullmatch(finding.get("unit_id") or "")
    entries = (structure.get(m.group(1)) or []) if m else []
    entry = entries[int(m.group(2))] if m and int(m.group(2)) < len(entries) else None

    if entry is not None:
        highlights = entry.get("highlights") or []
        h = int(m.group(3)) if m.group(3) is not None else None
        span = highlights[h] if h is not None and h < len(highlights) else entry
        label = f"{_ENTRY_KIND[m.group(1)]}：{entry.get('name') or '未命名'}（{entry.get('role') or '角色未写'}）"
        entry_spans = [(entry["char_start"], entry["char_end"])]
        sentence = (span["char_start"], span["char_end"])
    else:
        label = "全部工作 / 项目经历"
        entry_spans = [(e["char_start"], e["char_end"]) for e in (structure.get("work") or []) + (structure.get("projects") or [])]
        sentence = _line_at(full_text, finding["char_start"]) if finding.get("char_start") is not None else (None, None)

    entry_text = "\n".join(masked_text[s:e] for s, e in entry_spans) or "（简历里没有工作 / 项目经历）"
    user = prompts.ADVICE_FINDING_USER.format(
        job_title=job_title or "未指定", entry_label=label, entry_text=entry_text,
        sentence=_slice(masked_text, *sentence) or finding["title"],
        title=finding["title"], description=finding.get("description") or "",
        evidence=_slice(masked_text, finding.get("char_start"), finding.get("char_end")) or "（针对整份简历）")
    original = "\n".join(full_text[s:e] for s, e in entry_spans) + "\n" + _slice(full_text, *sentence)
    return AdvicePrompt([("system", fill(prompts.ADVICE_FINDING_SYSTEM, domain)), ("user", user)], original, "改成")


def gap_prompt(item: dict, requirement: dict | None, full_text: str, masked_text: str,
               job_title: str | None, *, domain: Domain = DEFAULT) -> AdvicePrompt:
    """item：match_reports.items 里没满足 / 部分满足的一条；requirement：岗位里对应的要求项（取 JD 原话，可能已被删）。"""
    quote = (requirement or {}).get("quote") or item["content"]
    evidence = _slice(masked_text, item.get("char_start"), item.get("char_end"))
    user = prompts.ADVICE_GAP_USER.format(
        job_title=job_title or "未指定", content=item["content"], req_type=REQ_TYPE_LABEL.get(item.get("req_type"), "要求"),
        quote=quote, status="缺失" if item["status"] == "miss" else "部分满足", reason=item.get("reason") or "无",
        evidence=f"「{evidence}」" if evidence else "无", resume=masked_text)
    original = f"{full_text}\n{item['content']}\n{quote}"
    return AdvicePrompt([("system", fill(prompts.ADVICE_GAP_SYSTEM, domain)), ("user", user)], original, "怎么补")


def fix_numbers(text: str, section: str, original: str) -> tuple[str, int]:
    """把【section】一段里原文没有的数字换成【数值】，返回 (新全文, 换掉的个数)。段标题之外的文字原样保留。"""
    parts = _SECTION.split(text)              # [开头, 段名, 内容, 段名, 内容, ...]
    replaced = 0
    for i in range(1, len(parts), 2):
        if parts[i] == section:
            parts[i + 1], n = mask_new_numbers(parts[i + 1], original)
            replaced += n
    rebuilt = parts[0] + "".join(f"【{parts[i]}】{parts[i + 1]}" for i in range(1, len(parts), 2))
    return rebuilt, replaced


def mask_new_numbers(text: str, original: str, *, keep_digits: bool = False) -> tuple[str, int]:
    """text 里 original 没有出现过的数字换成【数值】，返回 (新文本, 换掉的个数)。
    【】里的内容本来就是留给用户填的，不动。模拟面试的"参考答法"也用它，那里讲的是技术细节，
    keep_digits=True 放过单个数字（"影响行数为 0"、"重试 3 次"），编造的成果数据很少只有一位。"""
    allowed = set(NUMBER.findall(original))
    replaced = 0

    def fix(m: re.Match) -> str:
        nonlocal replaced
        if m.group(0) in allowed or (keep_digits and len(m.group(0)) == 1):
            return m.group(0)
        replaced += 1
        return PLACEHOLDER

    pieces = _BRACKETED.split(text)
    return "".join(p if p.startswith("【") else NUMBER.sub(fix, p) for p in pieces), replaced
