"""LangGraph 的 State 定义。

带 Annotated[..., add] 的字段是"可并行写回"的：N 个 review_unit 分支同时返回各自的增量，
LangGraph 用 add 把它们合并。没有 reducer 的字段若被多个并行分支同时写，会直接报错——
所以凡是并行分支要写的字段，都必须在这里声明 reducer。
"""
from __future__ import annotations

from operator import add
from typing import Annotated, Literal, TypedDict

from app.diagnose.types import Finding, ReviewUnit

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
