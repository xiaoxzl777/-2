"""面试报告：分数由 rubric 的纯函数聚合；模型只写文字总结（表现好的 / 需要加强 / 和简历问题的关联）。

不让模型打总分：总分要能说清楚是怎么来的，而且同样的问答每次算出来都一样。
文字总结失败不影响报告：分数、逐题回顾照常，总结部分留空（summary_ok = False），关联用固定的一句话。
"和简历问题的关联"只挑得分低于及格线、并且来源是简历问题 / 岗位要求的话题——这两类在结果页上都能点开看修改建议。
"""
from __future__ import annotations

import logging
from datetime import datetime

from pydantic import BaseModel, Field

from app.interview import rubric
from app.interview.materials import find_source
from app.llm import prompts
from app.llm.client import LLMClient, LLMError

logger = logging.getLogger("app.interview")

ANSWER_PREVIEW = 300        # 总结时每题回答最多带多少字
LINK_BELOW = 60             # 话题分低于它才去关联简历问题 / 岗位差距
DEFAULT_LINK = "这个话题面试里答得不理想，结果页上对应的这一条值得先改。"


class _Point(BaseModel):
    title: str = Field(min_length=1, max_length=40)
    detail: str = Field(default="", max_length=200)


class _Link(BaseModel):
    ref: str
    text: str = Field(min_length=1, max_length=200)


class _SummaryOut(BaseModel):
    strengths: list[_Point] = []
    weaknesses: list[_Point] = []
    links: list[_Link] = []


def build_report(*, materials: dict, plan: list[dict], history: list[dict], mode: str, threshold: float,
                 llm: LLMClient | None, model: str | None = None, ref: tuple[str, int] | None = None,
                 early: bool = False) -> tuple[dict, float]:
    """返回 (report, 花费)。llm 为 None 时不写文字总结（放弃的面试在启动清理时出报告，不值得再花钱）。"""
    scores = rubric.topic_scores(plan, history)
    overall = rubric.overall_score(scores)
    candidates = _link_candidates(materials, plan, scores)

    summary, cost = None, 0.0
    if llm is not None and history:
        try:
            summary, cost = _summarize(llm, materials, plan, history, scores, candidates, model=model, ref=ref)
        except LLMError:
            logger.exception("面试总结生成失败 %s", ref)

    texts = {link.ref: link.text.strip() for link in summary.links} if summary else {}
    report = {
        "overall": overall, "verdict": rubric.verdict(mode, overall, threshold, complete=None not in scores),
        "threshold": threshold, "mode": mode,
        "topics": [{"idx": t["idx"], "label": t["label"], "source": t["source"], "score": s}
                   for t, s in zip(plan, scores)],
        "strengths": [p.model_dump() for p in summary.strengths[:3]] if summary else [],
        "weaknesses": [p.model_dump() for p in summary.weaknesses[:3]] if summary else [],
        "links": [{**c, "text": texts.get(c["key"]) or DEFAULT_LINK} for c in candidates],
        "answered": len(history), "early": early, "summary_ok": summary is not None,
        "prompt_version": prompts.INTERVIEW_VERSION, "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    for link in report["links"]:
        link.pop("key")
    return report, cost


def _link_candidates(materials: dict, plan: list[dict], scores: list[int | None]) -> list[dict]:
    out = []
    for t, s in zip(plan, scores):
        if s is None or s >= LINK_BELOW or t["source"] not in ("finding", "requirement"):
            continue
        item = find_source(materials, t["source"], t["ref"]) or {}
        label = item.get("quote") if t["source"] == "finding" else item.get("content")
        out.append({"key": t["ref"], "kind": t["source"], "ref_id": item.get("id"),
                    "topic_idx": t["idx"], "label": label or t["label"]})
    return out


def _summarize(llm: LLMClient, materials: dict, plan: list[dict], history: list[dict], scores: list[int | None],
               candidates: list[dict], *, model: str | None, ref: tuple[str, int] | None) -> tuple[_SummaryOut | None, float]:
    topics = "\n".join(f"{t['idx'] + 1}. {t['label']}：{'没聊到' if s is None else s}" for t, s in zip(plan, scores))
    turns = []
    for h in history:
        ev = h.get("evaluation") or {}
        head = f"[话题 {h['topic_idx'] + 1}{' · 追问' if h['depth'] else ''}] 问：{h['question']}"
        if ev.get("skipped"):
            turns.append(f"{head}\n答：（跳过了）")
            continue
        turns.append(f"{head}\n答：{(h['answer'] or '')[:ANSWER_PREVIEW]}\n"
                     f"得分 {ev.get('score')}；好在：{ev.get('good') or '无'}；不足：{ev.get('bad') or '无'}")
    links = "\n".join(f"{c['key']}  {'简历问题' if c['kind'] == 'finding' else '岗位要求'}：{c['label']}"
                      for c in candidates) or "（无）"
    messages = [("system", prompts.INTERVIEW_REPORT_SYSTEM),
                ("user", prompts.INTERVIEW_REPORT_USER.format(job_title=materials["job_title"], topics=topics,
                                                              turns="\n\n".join(turns), links=links))]
    result = llm.invoke("interview_report", messages, prompt_version=prompts.INTERVIEW_VERSION, schema=_SummaryOut,
                        ref=ref, model=model, temperature=0.3, use_cache=False)
    if result.parsed is None:
        logger.warning("面试总结的输出不合格：%s", result.parse_error)
        return None, result.cost
    return result.parsed, result.cost
