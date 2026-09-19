"""诊断工作流（图 A 的 diagnose 子图，也可单独运行）。

    START ─► rule_scan ─► plan_review ─┬─(Send × N)─► review_unit ─┐
                                       │                           ├─► merge_findings ─► score ─► END
                                       └─(没有要审的)───────────────┘

三种 mode 共用同一张图，只在两处各有一个 if：
    llm_only  → rule_scan 直接返回空
    rule_only → plan_review 不选任何单元，于是直接去 merge_findings
消融实验切换的是参数，不是代码路径。

领域层：节点只收发纯数据，不碰数据库；落库由 diagnose_service 在图外完成。
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.config import settings
from app.diagnose.llm_review import review_unit
from app.diagnose.rules import RuleContext, run_rules
from app.diagnose.scorer import score
from app.diagnose.types import Finding, iter_units
from app.graphs.state import DiagnoseState, ReviewUnitInput
from app.llm.client import LLMClient

RETRY_COST_MARGIN = 1.5     # 预估成本时给"失败重试"留的余量
DUPLICATE_OVERLAP = 0.5     # 两条 finding 的证据区间重叠超过较短者的一半，视为同一个问题


def _rule_scan(state: DiagnoseState) -> dict:
    if state["mode"] == "llm_only":
        return {"rule_findings": []}
    ctx = RuleContext(state["structure"], state["full_text"], state.get("ats_signals") or {}, state.get("page_count"))
    return {"rule_findings": run_rules(ctx)}


def _plan_review(state: DiagnoseState) -> dict:
    """决定哪些单元送给模型。成本只在这里预检一次——分发出去的就让它跑完，分支内部不再判断。"""
    if state["mode"] == "rule_only":
        return {"review_units": [], "units_total": 0, "units_skipped": 0}
    units = iter_units(state["structure"], state["full_text"])
    affordable = int(state["cost_limit"] / (settings.UNIT_COST_EST * RETRY_COST_MARGIN))
    return {"review_units": units[:affordable], "units_total": len(units),
            "units_skipped": max(0, len(units) - affordable)}


def _dispatch(state: DiagnoseState) -> list[Send] | str:
    """条件边：每个待审单元发一个并行分支；没有要审的就直接去合并。"""
    units = state["review_units"]
    if not units:
        return "merge_findings"

    by_unit: dict[str, list[str]] = {}
    for f in state.get("rule_findings") or []:
        if f.unit_id:
            by_unit.setdefault(f.unit_id, []).append(f.title)
    return [
        Send("review_unit", ReviewUnitInput(
            unit=u, rule_summary="\n".join(f"- {t}" for t in by_unit.get(u.unit_id, [])),
            full_text=state["full_text"], masked_text=state["masked_text"], job_title=state.get("job_title"),
            model=state.get("model"), diagnosis_id=state.get("diagnosis_id")))
        for u in units
    ]



def _overlap_ratio(a: Finding, b: Finding) -> float:
    if None in (a.char_start, a.char_end, b.char_start, b.char_end):
        return 0.0
    shared = min(a.char_end, b.char_end) - max(a.char_start, b.char_start)
    shortest = min(a.char_end - a.char_start, b.char_end - b.char_start)
    return shared / shortest if shared > 0 and shortest > 0 else 0.0


def _merge_findings(state: DiagnoseState) -> dict:
    """规则与模型指向同一处、且属于同一维度时只留规则那条：规则的结论是确定的。"""
    rules = list(state.get("rule_findings") or [])
    merged = rules[:]
    for f in state.get("llm_findings") or []:
        duplicate = any(f.category == r.category and _overlap_ratio(f, r) >= DUPLICATE_OVERLAP for r in rules)
        if not duplicate:
            merged.append(f)
    order = {"high": 0, "medium": 1, "low": 2}
    merged.sort(key=lambda f: (order[f.severity], f.char_start if f.char_start is not None else 1 << 30))
    return {"findings": merged}


def _score(state: DiagnoseState) -> dict:
    unit_count = len(iter_units(state["structure"], state["full_text"]))
    overall, detail = score(state["findings"], state["mode"], unit_count)
    return {"overall_score": overall, "score_detail": detail}


def build_diagnose_graph(llm: LLMClient):
    """llm 通过闭包传给节点，State 里只放纯数据。"""

    def _review_unit(payload: ReviewUnitInput) -> dict:
        ref = ("diagnosis", payload["diagnosis_id"]) if payload.get("diagnosis_id") else None
        r = review_unit(payload["unit"], payload["full_text"], payload["masked_text"], llm,
                        job_title=payload.get("job_title"), rule_summary=payload["rule_summary"],
                        model=payload.get("model"), ref=ref)
        return {"llm_findings": r.verified, "rejected_findings": r.rejected,
                "schema_errors": r.schema_errors, "cost": r.cost}

    graph = StateGraph(DiagnoseState)
    graph.add_node("rule_scan", _rule_scan)
    graph.add_node("plan_review", _plan_review)
    graph.add_node("review_unit", _review_unit)
    graph.add_node("merge_findings", _merge_findings)
    graph.add_node("score", _score)

    graph.add_edge(START, "rule_scan")
    graph.add_edge("rule_scan", "plan_review")
    graph.add_conditional_edges("plan_review", _dispatch, ["review_unit", "merge_findings"])
    graph.add_edge("review_unit", "merge_findings")
    graph.add_edge("merge_findings", "score")
    graph.add_edge("score", END)
    return graph.compile()


def initial_state(*, structure: dict, full_text: str, masked_text: str, mode: str = "hybrid",
                  ats_signals: dict | None = None, page_count: int | None = None, job_title: str | None = None,
                  model: str | None = None, diagnosis_id: int | None = None,
                  cost_limit: float | None = None) -> DiagnoseState:
    return DiagnoseState(
        diagnosis_id=diagnosis_id, mode=mode, model=model, job_title=job_title, full_text=full_text,
        masked_text=masked_text, structure=structure, ats_signals=ats_signals or {}, page_count=page_count,
        cost_limit=settings.DIAGNOSE_COST_LIMIT if cost_limit is None else cost_limit,
        llm_findings=[], rejected_findings=[], schema_errors=0, cost=0.0,
    )
