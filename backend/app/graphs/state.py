"""LangGraph 的 State 定义。

带 Annotated[..., add] 的字段是"可并行写回"的：N 个 review_unit 分支同时返回各自的增量，
LangGraph 用 add 把它们合并。没有 reducer 的字段若被多个并行分支同时写，会直接报错——
所以凡是并行分支要写的字段，都必须在这里声明 reducer。
"""
from __future__ import annotations

from operator import add
from typing import Annotated, Literal, TypedDict

from app.diagnose.types import Finding, ReviewUnit
from app.matching.matcher import MatchItem

DiagnoseMode = Literal["rule_only", "llm_only", "hybrid"]


class DiagnoseState(TypedDict, total=False):
    # ── 输入 ──
    diagnosis_id: int | None
    mode: DiagnoseMode
    model: str | None
    job_title: str | None
    full_text: str
    masked_text: str            # 与 full_text 等长的 PII 掩码版本，发给模型用
    structure: dict
    ats_signals: dict
    page_count: int | None
    cost_limit: float

    # ── 过程与输出 ──
    review_units: list[ReviewUnit]   # plan_review 选出的、要送给模型的单元
    units_total: int
    units_skipped: int          # 成本预检截掉的单元数；> 0 时最终状态为 partial
    rule_findings: list[Finding]
    llm_findings: Annotated[list[Finding], add]
    rejected_findings: Annotated[list[Finding], add]
    schema_errors: Annotated[int, add]
    cost: Annotated[float, add]
    findings: list[Finding]     # 合并去重后的最终结果
    overall_score: float | None
    score_detail: dict


class ReviewUnitInput(TypedDict):
    """dispatch 用 Send 发给每个 review_unit 分支的载荷（分支拿不到完整的 State）。"""

    unit: ReviewUnit
    rule_summary: str
    full_text: str
    masked_text: str
    job_title: str | None
    model: str | None
    diagnosis_id: int | None


# ───────────────────────── 匹配 ─────────────────────────

MatchMode = Literal["dict_only", "llm_fulltext", "llm_rag", "hybrid"]


class MatchState(TypedDict, total=False):
    # ── 输入 ──
    match_report_id: int | None
    mode: MatchMode
    model: str | None
    requirements: list[dict]    # jobs.requirements
    structure: dict
    full_text: str
    masked_text: str

    # ── 过程与输出 ──
    rule_items: list[MatchItem]          # 规则通道判定了的
    pending: list[dict]                  # 规则判不了、留给模型的要求项
    judged: Annotated[list[MatchItem], add]   # RAG 判定的结果：M 个并行分支各写一条
    rechecked: list[MatchItem]           # 全文判定 / 复核的结果，按 requirement_id 覆盖 judged
    llm_item_count: int
    hallucination_count: Annotated[int, add]
    cost: Annotated[float, add]
    items: list[MatchItem]               # 最终结果，按要求项顺序
    overall_match: float | None
    dimension_scores: dict


class JudgeInput(TypedDict):
    """dispatch 用 Send 发给每个 judge_requirement 分支的载荷。"""

    requirement: dict
    full_text: str
    model: str | None
    match_report_id: int | None
