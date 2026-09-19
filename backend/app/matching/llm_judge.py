"""匹配的 LLM 通道：规则判不了的要求项，连同简历全文一次交给模型判断。

模型的结论必须能落到简历原文上（系统不变量⑥）：说"满足 / 部分满足"就得逐字引用依据，
引用在原文里找不到 → 记一次幻觉，这条按"未满足"处理。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.diagnose.evidence import locate_span
from app.llm import prompts
from app.llm.client import LLMClient
from app.matching.matcher import MatchItem


class _Result(BaseModel):
    id: int
    status: Literal["hit", "partial", "miss"]
    evidence_quote: str | None = None
    reason: str = Field(default="", max_length=200)


class _FulltextOut(BaseModel):
    results: list[_Result]


@dataclass(slots=True)
class JudgeResult:
    items: list[MatchItem] = field(default_factory=list)
    hallucinations: int = 0
    cost: float = 0.0


def requirement_query(req: dict) -> str:
    """给模型看的要求文本：模型复述的 content，加上 JD 里的原话（信息更全）。"""
    quote = req.get("quote") or ""
    return req["content"] if not quote or quote in req["content"] else f"{req['content']}（JD 原文：{quote}）"


def judge_with_fulltext(reqs: list[dict], full_text: str, masked_text: str, llm: LLMClient, *,
                        model: str | None = None, ref: tuple[str, int] | None = None) -> JudgeResult:
    """一次调用判定多条要求。模型漏答的要求按 miss 处理。reqs 为空时不调模型。"""
    if not reqs:
        return JudgeResult()
    listing = "\n".join(f"{r['id']}. {requirement_query(r)}" for r in reqs)
    messages = [("system", prompts.MATCH_SYSTEM),
                ("user", prompts.MATCH_USER.format(requirements=listing, resume=masked_text))]
    out, cost = _invoke(llm, messages, model, ref)
    answers = {r.id: r for r in out.results} if out else {}

    result = JudgeResult(cost=cost)
    for req in reqs:
        answer = answers.get(req["id"])
        if answer is None or answer.status == "miss":
            reason = answer.reason if answer else "模型没有给出这条要求的结论" if out else "模型输出无法解析"
            result.items.append(_miss(req, reason))
            continue
        # 掩码不改变长度，所以在掩码文本上定位到的区间可以直接用来切原文
        span = locate_span(answer.evidence_quote or "", masked_text)
        if span is None:
            result.hallucinations += 1
            result.items.append(_miss(req, "模型引用的依据在简历原文中找不到，已作废"))
            continue
        result.items.append(MatchItem(req["id"], answer.status, "fulltext", answer.reason,
                                      full_text[span.start:span.end], span.start, span.end))
    return result


def _invoke(llm: LLMClient, messages: list, model: str | None,
            ref: tuple[str, int] | None) -> tuple[_FulltextOut | None, float]:
    """输出不合格时带着原因重试一次；仍不合格返回 None（调用方按 miss 处理，不让格式问题拖垮整次匹配）。"""
    cost = 0.0
    for attempt in range(2):
        result = llm.invoke("match", messages, prompt_version=prompts.MATCH_VERSION, schema=_FulltextOut,
                            ref=ref, model=model)
        cost += result.cost
        if result.parsed is not None:
            return result.parsed, cost
        if attempt == 0:
            messages = [*messages, ("assistant", result.text[:2000]),
                        ("user", prompts.MATCH_RETRY.format(error=result.parse_error))]
    return None, cost


def _miss(req: dict, reason: str) -> MatchItem:
    return MatchItem(req["id"], "miss", "fulltext", reason or "没有找到依据")
