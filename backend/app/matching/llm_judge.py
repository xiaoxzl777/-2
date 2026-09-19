"""匹配的 LLM 通道：规则判不了的要求项交给模型，但模型的结论必须能落到简历原文上（系统不变量⑥）。

两种判定方式，对应消融实验里的两组对照：
  · judge_with_candidates  RAG：只给模型看检索出的几个片段，它指出依据是第几个 → 证据即该片段的 char 区间
  · judge_with_fulltext    不用 RAG：给模型看简历全文，它逐字引用依据 → 经 locate_span 定位
模型说 hit / partial 却给不出合法依据（编号不在候选里、引用在原文里找不到）→ 记一次幻觉，按 miss 处理。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.diagnose.evidence import locate_span
from app.llm import prompts
from app.llm.client import LLMClient
from app.matching.matcher import MatchItem
from app.matching.units import Candidate

Status = Literal["hit", "partial", "miss"]


class _JudgeOut(BaseModel):
    status: Status
    unit_no: int | None = None
    reason: str = Field(default="", max_length=200)


class _FulltextResult(BaseModel):
    id: int
    status: Status
    evidence_quote: str | None = None
    reason: str = Field(default="", max_length=200)


class _FulltextOut(BaseModel):
    results: list[_FulltextResult]


@dataclass(slots=True)
class JudgeResult:
    items: list[MatchItem] = field(default_factory=list)
    hallucinations: int = 0
    cost: float = 0.0


def requirement_query(req: dict) -> str:
    """检索与判定用的要求文本：模型复述的 content，加上 JD 里的原话（信息更全）。"""
    quote = req.get("quote") or ""
    return req["content"] if not quote or quote in req["content"] else f"{req['content']}（JD 原文：{quote}）"


def judge_with_candidates(req: dict, candidates: list[Candidate], full_text: str, llm: LLMClient, *,
                          model: str | None = None, ref: tuple[str, int] | None = None) -> JudgeResult:
    if not candidates:
        return JudgeResult([_miss(req, "rag", "简历中没有检索到相关内容")])
    listing = "\n".join(f"[#{n}] {f'（{c.entry_name}）' if c.entry_name else ''}{c.text}"
                        for n, c in enumerate(candidates, 1))
    messages = [("system", prompts.MATCH_JUDGE_SYSTEM),
                ("user", prompts.MATCH_JUDGE_USER.format(requirement=requirement_query(req), candidates=listing))]
    out, cost = _invoke(llm, messages, _JudgeOut, model, ref)
    if out is None:
        return JudgeResult([_miss(req, "rag", "模型输出无法解析")], cost=cost)
    if out.status == "miss":
        return JudgeResult([_miss(req, "rag", out.reason)], cost=cost)
    if out.unit_no is None or not 1 <= out.unit_no <= len(candidates):
        return JudgeResult([_miss(req, "rag", "模型给出的依据不在检索结果中，已作废")], hallucinations=1, cost=cost)
    c = candidates[out.unit_no - 1]
    item = MatchItem(req["id"], out.status, "rag", out.reason, full_text[c.char_start:c.char_end],
                     c.char_start, c.char_end, c.unit_id)
    return JudgeResult([item], cost=cost)


def judge_with_fulltext(reqs: list[dict], full_text: str, masked_text: str, llm: LLMClient, *,
                        model: str | None = None, ref: tuple[str, int] | None = None) -> JudgeResult:
    """一次调用判定多条要求。模型漏掉的要求按 miss 处理。"""
    if not reqs:
        return JudgeResult()
    listing = "\n".join(f"{r['id']}. {requirement_query(r)}" for r in reqs)
    messages = [("system", prompts.MATCH_FULLTEXT_SYSTEM),
                ("user", prompts.MATCH_FULLTEXT_USER.format(requirements=listing, resume=masked_text))]
    out, cost = _invoke(llm, messages, _FulltextOut, model, ref)
    answers = {r.id: r for r in out.results} if out else {}

    result = JudgeResult(cost=cost)
    for req in reqs:
        answer = answers.get(req["id"])
        if answer is None or answer.status == "miss":
            result.items.append(_miss(req, "fulltext", answer.reason if answer else "模型没有给出这条要求的结论"))
            continue
        # 掩码不改变长度，所以在掩码文本上定位到的区间可以直接用来切原文
        span = locate_span(answer.evidence_quote or "", masked_text)
        if span is None:
            result.hallucinations += 1
            result.items.append(_miss(req, "fulltext", "模型引用的依据在简历原文中找不到，已作废"))
            continue
        result.items.append(MatchItem(req["id"], answer.status, "fulltext", answer.reason,
                                      full_text[span.start:span.end], span.start, span.end))
    return result


def _invoke(llm: LLMClient, messages: list, schema: type[BaseModel], model: str | None,
            ref: tuple[str, int] | None) -> tuple[BaseModel | None, float]:
    """输出不合格时带着原因重试一次；仍不合格返回 None（调用方按 miss 处理，不让一条要求拖垮整次匹配）。"""
    cost = 0.0
    for attempt in range(2):
        result = llm.invoke("match", messages, prompt_version=prompts.MATCH_VERSION, schema=schema, ref=ref, model=model)
        cost += result.cost
        if result.parsed is not None:
            return result.parsed, cost
        if attempt == 0:
            messages = [*messages, ("assistant", result.text[:2000]),
                        ("user", prompts.MATCH_RETRY.format(error=result.parse_error))]
    return None, cost


def _miss(req: dict, matched_by: str, reason: str) -> MatchItem:
    return MatchItem(req["id"], "miss", matched_by, reason or "没有找到依据")
