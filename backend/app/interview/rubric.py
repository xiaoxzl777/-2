"""评分：模型按 rubric 给一题打分，代码核对依据；分数聚合是纯函数（docs/04-design 5.9）。

防幻觉与诊断同一套（系统不变量⑥）：模型的每条依据必须逐字引用候选人的回答，经 locate_span 定位。
一条都对不上 → 带着原因重试一次 → 还是不行，三项都给中性 3 分并标 low_evidence（聚合时权重减半）：
没有依据的分数不可信，但也不能因为模型没引用好就判候选人 0 分。
"参考答法"里候选人没说过的数字换成【数值】，和具体建议同一个复检函数。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.diagnose.evidence import locate_span
from app.llm import prompts
from app.llm.client import LLMClient
from app.rewrite.advice import mask_new_numbers

DIMENSIONS = ("correctness", "depth", "clarity")
NEUTRAL = 3
LOW_EVIDENCE_WEIGHT = 0.5


class _Scores(BaseModel):
    correctness: int = Field(ge=0, le=5)
    depth: int = Field(ge=0, le=5)
    clarity: int = Field(ge=0, le=5)


class _EvalOut(BaseModel):
    scores: _Scores
    evidence: list[str] = []
    good: str = Field(default="", max_length=200)
    bad: str = Field(default="", max_length=200)
    better_answer: str = Field(default="", max_length=800)
    decision: Literal["followup", "next"] = "next"


def turn_score(scores: dict) -> int:
    """一题的分：三项平均 × 20，0–100。"""
    return round(sum(scores[d] for d in DIMENSIONS) / len(DIMENSIONS) * 20)


def skipped_evaluation() -> dict:
    """跳过 / 空答：不调模型，记 0 分（否则跳过难题反而能拉高平均分），直接换话题。"""
    return {"skipped": True, "scores": None, "score": 0, "evidence": [], "good": "", "bad": "这题跳过了",
            "better_answer": "", "decision": "next", "low_evidence": False}


def evaluate(llm: LLMClient, *, job_title: str, topic: dict, question: str, answer: str,
             model: str | None = None, ref: tuple[str, int] | None = None) -> tuple[dict, float]:
    """返回 (evaluation, 花费)。模型两次都没给出合法 JSON 时抛 ValueError，由调用方当失败处理。"""
    messages = [("system", prompts.INTERVIEW_EVAL_SYSTEM),
                ("user", prompts.INTERVIEW_EVAL_USER.format(job_title=job_title, label=topic["label"],
                                                            intent=topic["intent"], question=question, answer=answer))]
    cost, parsed, evidence = 0.0, None, []
    for attempt in range(2):
        result = llm.invoke("interview_eval", messages, prompt_version=prompts.INTERVIEW_VERSION, schema=_EvalOut,
                            ref=ref, model=model, temperature=0.0, use_cache=False)
        cost += result.cost
        if result.parsed is None:
            retry = prompts.JSON_RETRY.format(error=result.parse_error)
        else:
            parsed = result.parsed
            evidence, missing = _verify(parsed.evidence, answer)
            if evidence:
                break
            retry = prompts.INTERVIEW_EVAL_RETRY.format(missing="、".join(f"「{q}」" for q in missing) or "（没有给出）")
        if attempt == 0:
            messages = [*messages, ("assistant", result.text[:2000]), ("user", retry)]
    if parsed is None:
        raise ValueError(f"评分输出两次都不合格：{result.parse_error}")

    scores = parsed.scores.model_dump()
    low_evidence = not evidence
    if low_evidence:
        scores = dict.fromkeys(DIMENSIONS, NEUTRAL)
    better, violations = mask_new_numbers(parsed.better_answer.strip(), f"{question}\n{answer}", keep_digits=True)
    return {"skipped": False, "scores": scores, "score": turn_score(scores), "evidence": evidence,
            "good": parsed.good.strip(), "bad": parsed.bad.strip(), "better_answer": better,
            "number_violations": violations, "decision": parsed.decision, "low_evidence": low_evidence}, cost


def _verify(quotes: list[str], answer: str) -> tuple[list[dict], list[str]]:
    kept, missing = [], []
    for q in quotes[:3]:
        span = locate_span(q, answer)
        if span is None:
            missing.append(q)
        else:
            kept.append({"quote": answer[span.start:span.end], "char_start": span.start, "char_end": span.end,
                         "verify_result": span.method})
    return kept, missing


def topic_scores(plan: list[dict], history: list[dict]) -> list[int | None]:
    """每个话题的分 = 该话题各题分的加权平均（low_evidence 的题权重减半）；没问到的话题为 None。"""
    scores: list[int | None] = []
    for t in plan:
        turns = [h["evaluation"] for h in history if h["topic_idx"] == t["idx"] and h.get("evaluation")]
        weights = [LOW_EVIDENCE_WEIGHT if e.get("low_evidence") else 1.0 for e in turns]
        scores.append(round(sum(e["score"] * w for e, w in zip(turns, weights)) / sum(weights)) if turns else None)
    return scores


def overall_score(scores: list[int | None]) -> int:
    """综合分 = 问到了的话题的平均。提前结束时没聊到的话题不计。"""
    reached = [s for s in scores if s is not None]
    return round(sum(reached) / len(reached)) if reached else 0


def verdict(mode: str, overall: int, threshold: float, complete: bool = True) -> str:
    """练习模式不下结论；没聊完所有话题就结束的也不下结论（incomplete）——否则答好一题就结束也能"通过"。
    其余只看技术面分数过没过线。"""
    if mode == "practice":
        return "practice"
    if not complete:
        return "incomplete"
    return "pass" if overall >= threshold else "fail"
