"""匹配工作流（图 A 的 match 子图，也可单独运行）。三步直线：

    START ─► rule_match ─► judge_fulltext ─► score_match ─► END
             规则先判        规则判不了的要求，连同简历全文      公式算分
             （不花钱）      一次交给模型判断

三种 mode 共用这张图，差别只在 rule_match 留下多少"待判定"的要求：
    dict_only     只用规则，判不了的直接记 miss，不调模型      基线
    llm_fulltext  跳过规则，全部要求交给模型                   对照：只用模型
    hybrid        规则只判十拿九稳的，其余交给模型              线上默认

为什么不用 RAG：简历只有一两千字，全文放进 prompt 毫无压力。实测（单份样本）"逐条检索再判断"要几十次调用，
更贵更慢，还会因为检索漏掉片段而误判；"全文一次判断"只要一次调用。检索留给真正资料多的地方（面试材料）。

领域层：节点只收发纯数据，不碰数据库。
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.graphs.state import MatchState
from app.llm.client import LLMClient
from app.matching.llm_judge import judge_with_fulltext
from app.matching.matcher import MatchItem, match_by_rules, score_match


def _rule_match(state: MatchState) -> dict:
    mode, requirements = state["mode"], state["requirements"]
    if mode == "llm_fulltext":
        return {"rule_items": [], "pending": requirements}

    decided: list[MatchItem] = []
    pending: list[dict] = []
    for req in requirements:
        # hybrid 后面还有模型兜底，规则只在十拿九稳时下结论（strict）；dict_only 则能判的全判
        item = match_by_rules(req, state["structure"], state["full_text"], strict=mode == "hybrid")
        if item is not None:
            decided.append(item)
        elif mode == "dict_only":
            decided.append(MatchItem(req["id"], "miss", None, "规则无法判定（未启用模型）"))
        else:
            pending.append(req)
    return {"rule_items": decided, "pending": pending}


def _score_match(state: MatchState) -> dict:
    by_id = {i.requirement_id: i for i in [*state["rule_items"], *state["judged"]]}
    items = [by_id[r["id"]] for r in state["requirements"] if r["id"] in by_id]      # 按要求项的顺序
    overall, by_category = score_match(state["requirements"], items)
    return {"items": items, "overall_match": overall, "dimension_scores": by_category}


def build_match_graph(llm: LLMClient):
    """llm 通过闭包传给节点，State 里只放纯数据。"""

    def _judge_fulltext(state: MatchState) -> dict:
        ref = ("match_report", state["match_report_id"]) if state.get("match_report_id") else None
        r = judge_with_fulltext(state["pending"], state["full_text"], state["masked_text"], llm,
                                model=state.get("model"), ref=ref)       # pending 为空时不会调模型
        return {"judged": r.items, "llm_item_count": len(state["pending"]),
                "hallucination_count": r.hallucinations, "cost": r.cost}

    graph = StateGraph(MatchState)
    graph.add_node("rule_match", _rule_match)
    graph.add_node("judge_fulltext", _judge_fulltext)
    graph.add_node("score_match", _score_match)
    graph.add_edge(START, "rule_match")
    graph.add_edge("rule_match", "judge_fulltext")
    graph.add_edge("judge_fulltext", "score_match")
    graph.add_edge("score_match", END)
    return graph.compile()


def initial_state(*, requirements: list[dict], structure: dict, full_text: str, masked_text: str,
                  mode: str = "hybrid", model: str | None = None, match_report_id: int | None = None) -> MatchState:
    return MatchState(match_report_id=match_report_id, mode=mode, model=model, requirements=requirements,
                      structure=structure, full_text=full_text, masked_text=masked_text)
