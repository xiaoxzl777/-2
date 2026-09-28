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

MatchMode = Literal["dict_only", "llm_fulltext", "hybrid"]


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
    rule_items: list[MatchItem]          # 规则判定了的
    pending: list[dict]                  # 规则判不了、留给模型的要求项
    judged: list[MatchItem]              # 模型判定的
    llm_item_count: int
    hallucination_count: int
    cost: float
    items: list[MatchItem]               # 最终结果，按要求项顺序
    overall_match: float | None
    dimension_scores: dict


# ───────────────────────── 模拟面试（图 B） ─────────────────────────

class InterviewState(TypedDict, total=False):
    # ── 输入（创建会话时定下，之后不变）──
    session_id: int
    mode: Literal["normal", "practice"]
    model: str | None
    materials: dict             # interview/materials.py：岗位要求、经历、简历问题、面经
    topic_count: int
    max_followup: int
    cost_limit: float
    threshold: float

    # ── 过程 ──
    plan: list[dict]            # [{idx, source, ref, label, intent}]
    topic_idx: int              # 当前话题；-1 = 还没开始
    depth: int                  # 0 = 主问题，1.. = 第几次追问
    context: list[str]          # 当前话题的参考材料（面经整段或检索到的几段）
    question: str
    answer: str
    skipped: bool
    evaluation: dict
    next_step: str              # decide 的结论：followup / next / finish
    history: Annotated[list[dict], add]   # 每答完一题追加一条 {topic_idx, depth, question, answer, skipped, evaluation}
    cost: Annotated[float, add]
    report: dict
