"""匹配工作流（图 A 的 match 子图，也可单独运行）。

    START ─► rule_match ─┬─(Send × M)─► judge_requirement ─► recheck_missing ─┐
                         ├─────────────► judge_fulltext ──────────────────────┼─► score_match ─► END
                         └─(没有要判的)────────────────────────────────────────┘

四种 mode 共用这张图，差别只在 rule_match 留下多少"待判定"的要求、以及条件边把它们送去哪里：
    dict_only     规则判不了的直接记 miss，不调模型                 基线
    llm_fulltext  跳过规则，全部要求连同简历全文一次交给模型           对照：不用 RAG
    llm_rag       跳过规则，逐条 召回 → 精排 → 判定                   对照：只用 RAG
    hybrid        规则只判十拿九稳的；剩下的走 RAG；RAG 判 miss 的再用全文复核一次（防检索漏掉）   线上默认

领域层：节点只收发纯数据。检索函数 retrieve 由 service 注入（它背后是 Chroma 与 embedding 接口），图不知道这些。
"""
from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.graphs.state import JudgeInput, MatchState
from app.llm.client import LLMClient
from app.matching.llm_judge import judge_with_candidates, judge_with_fulltext, requirement_query
from app.matching.matcher import MatchItem, match_by_rules, score_match
from app.matching.units import Candidate

Retrieve = Callable[[str], list[Candidate]]     # 要求文本 → 精排后的候选单元

_USES_RULES = ("dict_only", "hybrid")


def _rule_match(state: MatchState) -> dict:
    requirements = state["requirements"]
    if state["mode"] not in _USES_RULES:
        return {"rule_items": [], "pending": requirements, "llm_item_count": len(requirements)}

    decided: list[MatchItem] = []
    pending: list[dict] = []
    for req in requirements:
        item = match_by_rules(req, state["structure"], state["full_text"], strict=state["mode"] == "hybrid")
        if item is not None:
            decided.append(item)
        elif state["mode"] == "dict_only":
            decided.append(MatchItem(req["id"], "miss", None, "规则无法判定（未启用模型）"))
        else:
            pending.append(req)
    return {"rule_items": decided, "pending": pending, "llm_item_count": len(pending)}


def _dispatch(state: MatchState) -> list[Send] | str:
    pending = state["pending"]
    if not pending:
        return "score_match"
    if state["mode"] == "llm_fulltext":
        return "judge_fulltext"
    return [Send("judge_requirement", JudgeInput(requirement=req, full_text=state["full_text"], model=state.get("model"),
                                                 match_report_id=state.get("match_report_id")))
            for req in pending]


def _score_match(state: MatchState) -> dict:
    by_id = {i.requirement_id: i for i in [*state.get("rule_items", []), *state.get("judged", [])]}
    by_id.update({i.requirement_id: i for i in state.get("rechecked", [])})       # 复核结果覆盖 RAG 的 miss
    items = [by_id[r["id"]] for r in state["requirements"] if r["id"] in by_id]
    overall, by_category = score_match(state["requirements"], items)
    return {"items": items, "overall_match": overall, "dimension_scores": by_category}


def build_match_graph(llm: LLMClient, retrieve: Retrieve | None = None):
    """llm 与 retrieve 通过闭包传给节点。dict_only / llm_fulltext 用不到检索，可以不传。"""

    def _ref(report_id: int | None) -> tuple[str, int] | None:
        return ("match_report", report_id) if report_id else None

    def _judge_requirement(payload: JudgeInput) -> dict:
        if retrieve is None:
            raise ValueError("llm_rag / hybrid 模式需要传入 retrieve")
        req = payload["requirement"]
        r = judge_with_candidates(req, retrieve(requirement_query(req)), payload["full_text"], llm,
                                  model=payload.get("model"), ref=_ref(payload.get("match_report_id")))
        return {"judged": r.items, "hallucination_count": r.hallucinations, "cost": r.cost}

    def _fulltext(state: MatchState, reqs: list[dict]) -> dict:
        r = judge_with_fulltext(reqs, state["full_text"], state["masked_text"], llm,
                                model=state.get("model"), ref=_ref(state.get("match_report_id")))
        return {"rechecked": r.items, "hallucination_count": r.hallucinations, "cost": r.cost}

    def _judge_fulltext(state: MatchState) -> dict:
        return _fulltext(state, state["pending"])

    def _recheck_missing(state: MatchState) -> dict:
        """检索可能漏掉相关经历：RAG 判为 miss 的，用全文再问一次。只有 hybrid 做；llm_rag 要保持"纯 RAG"以便对照。"""
        if state["mode"] != "hybrid":
            return {"rechecked": []}
        missed = {i.requirement_id for i in state.get("judged", []) if i.status == "miss"}
        return _fulltext(state, [r for r in state["pending"] if r["id"] in missed])

    graph = StateGraph(MatchState)
    graph.add_node("rule_match", _rule_match)
    graph.add_node("judge_requirement", _judge_requirement)
    graph.add_node("judge_fulltext", _judge_fulltext)
    graph.add_node("recheck_missing", _recheck_missing)
    graph.add_node("score_match", _score_match)

    graph.add_edge(START, "rule_match")
    graph.add_conditional_edges("rule_match", _dispatch, ["judge_requirement", "judge_fulltext", "score_match"])
    graph.add_edge("judge_requirement", "recheck_missing")
    graph.add_edge("recheck_missing", "score_match")
    graph.add_edge("judge_fulltext", "score_match")
    graph.add_edge("score_match", END)
    return graph.compile()


def initial_state(*, requirements: list[dict], structure: dict, full_text: str, masked_text: str,
                  mode: str = "hybrid", model: str | None = None, match_report_id: int | None = None) -> MatchState:
    return MatchState(match_report_id=match_report_id, mode=mode, model=model, requirements=requirements,
                      structure=structure, full_text=full_text, masked_text=masked_text,
                      judged=[], rechecked=[], hallucination_count=0, cost=0.0)
