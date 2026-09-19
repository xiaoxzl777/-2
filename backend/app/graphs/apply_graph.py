"""图 A：投递流水线。诊断与匹配互不依赖，并行跑；两条都完成后过初筛线。

                 ┌─► diagnose（诊断子图）─┐
    START ───────┤                       ├─► gate ─► END
                 └─► match（匹配子图） ───┘

两个子图各自可以单独运行（诊断接口、匹配接口、消融实验都直接调子图），这里只是把它们并行编排起来。
子图的 State 与这张图的 State 不同，所以用普通节点包一层：取输入 → invoke 子图 → 把整个输出放进一个字段。
两个分支写的是不同字段，不需要 reducer。

简历解析不在图里：上传时已经触发，apply_service 在跑图之前等它完成（解析要读文件、写数据库，不属于领域层）。
"未通过说明"也不在图里：它是对已落库的匹配明细与诊断结果的一种读法，由接口在读取时组装（带上数据库 id 才能点开改写）。
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.config import settings
from app.graphs import diagnose_graph, match_graph
from app.graphs.match_graph import Retrieve
from app.llm.client import LLMClient


class ApplyState(TypedDict, total=False):
    # ── 输入 ──
    diagnosis_id: int | None
    match_report_id: int | None
    diagnose_mode: str
    match_mode: str
    model: str | None
    job_title: str | None
    requirements: list[dict]
    structure: dict
    full_text: str
    masked_text: str
    ats_signals: dict
    page_count: int | None

    # ── 输出 ──
    diagnosis: dict             # 诊断子图的完整输出
    match: dict                 # 匹配子图的完整输出
    passed: bool


def _gate(state: ApplyState) -> dict:
    overall = state["match"]["overall_match"]
    return {"passed": overall is not None and overall >= settings.SCREEN_THRESHOLD}


def build_apply_graph(llm: LLMClient, retrieve: Retrieve | None = None):
    diagnose = diagnose_graph.build_diagnose_graph(llm)
    match = match_graph.build_match_graph(llm, retrieve)

    def _diagnose(state: ApplyState) -> dict:
        return {"diagnosis": diagnose.invoke(diagnose_graph.initial_state(
            structure=state["structure"], full_text=state["full_text"], masked_text=state["masked_text"],
            mode=state["diagnose_mode"], model=state.get("model"), job_title=state.get("job_title"),
            ats_signals=state.get("ats_signals"), page_count=state.get("page_count"),
            diagnosis_id=state.get("diagnosis_id")))}

    def _match(state: ApplyState) -> dict:
        return {"match": match.invoke(match_graph.initial_state(
            requirements=state["requirements"], structure=state["structure"], full_text=state["full_text"],
            masked_text=state["masked_text"], mode=state["match_mode"], model=state.get("model"),
            match_report_id=state.get("match_report_id")))}

    graph = StateGraph(ApplyState)
    graph.add_node("diagnose", _diagnose)
    graph.add_node("match", _match)
    graph.add_node("gate", _gate)
    graph.add_edge(START, "diagnose")
    graph.add_edge(START, "match")
    graph.add_edge(["diagnose", "match"], "gate")      # 两条分支都完成才往下
    graph.add_edge("gate", END)
    return graph.compile()
