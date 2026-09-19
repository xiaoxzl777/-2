"""JD 解析：一次模型调用把岗位描述拆成要求项，再逐条做确定性校验。

与诊断同一原则（系统不变量⑥）：模型给出的每条要求都必须附带 JD 原文的逐字引用，
引用定位不到、或声称的技能在 JD 里根本没出现 → 这条是模型编的，丢弃并计数。
技能类要求经词典回填 skill_id（词典里没有的留 None，匹配阶段交给 RAG + LLM 判定）；权重由 req_type 决定，不让模型给。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.diagnose.evidence import locate_span, normalize_for_match
from app.llm import prompts
from app.llm.client import LLMClient
from app.matching.skill_dict import SkillDict

MAX_REQUIREMENTS = 25
WEIGHTS = {"hard": 1.0, "plus": 0.5, "soft": 0.3}


class _Requirement(BaseModel):
    req_type: Literal["hard", "plus", "soft"]
    category: Literal["skill", "education", "experience", "other"]
    skill: str | None = None
    quote: str
    content: str = Field(min_length=1, max_length=200)


class _JdOut(BaseModel):
    requirements: list[_Requirement]


@dataclass(slots=True)
class JdParseResult:
    requirements: list[dict] = field(default_factory=list)
    rejected: int = 0            # 引用定位失败 / 技能不在 JD 中而被丢弃的条数
    cost: float = 0.0
    error: str | None = None     # 两次输出都不合格时的原因；此时 requirements 为空


def parse_jd(title: str, raw_text: str, llm: LLMClient, skills: SkillDict, *,
             model: str | None = None, ref: tuple[str, int] | None = None) -> JdParseResult:
    """raw_text 必须是已经定稿的文本：返回的 char 区间相对它。输出不合格时带着原因重试一次。"""
    messages = [("system", prompts.JD_SYSTEM), ("user", prompts.JD_USER.format(title=title, raw_text=raw_text))]
    out = JdParseResult()
    for attempt in range(2):
        result = llm.invoke("jd_parse", messages, prompt_version=prompts.JD_VERSION, schema=_JdOut, ref=ref, model=model)
        out.cost += result.cost
        if result.parsed is not None:
            out.requirements, out.rejected = _verify(result.parsed.requirements, raw_text, skills)
            return out
        if attempt == 0:
            messages = [*messages, ("assistant", result.text[:2000]),
                        ("user", prompts.JD_RETRY.format(error=result.parse_error))]
    out.error = result.parse_error
    return out


def _verify(items: list[_Requirement], raw_text: str, skills: SkillDict) -> tuple[list[dict], int]:
    haystack = normalize_for_match(raw_text)
    kept: list[dict] = []
    seen: set = set()
    rejected = 0
    for item in items[:MAX_REQUIREMENTS]:
        skill = ((item.skill or "").strip() or None) if item.category == "skill" else None
        span = locate_span(item.quote, raw_text)
        if span is None or (skill and normalize_for_match(skill) not in haystack):
            rejected += 1
            continue
        skill_id = skills.lookup(skill) if skill else None
        # 同一技能（或同一段原文里的同一句非技能要求）只留第一次出现的
        key = ("skill", skill_id or normalize_for_match(skill)) if skill else ("text", span.start, span.end, item.category)
        if key in seen:
            continue
        seen.add(key)
        kept.append({
            "id": len(kept) + 1, "req_type": item.req_type, "category": item.category, "content": item.content,
            "skill": skill, "skill_id": skill_id, "weight": WEIGHTS[item.req_type],
            "quote": raw_text[span.start:span.end], "char_start": span.start, "char_end": span.end,
        })
    return kept, rejected
