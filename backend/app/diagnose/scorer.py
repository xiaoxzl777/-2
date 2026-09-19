"""综合评分：由加权公式算出，不让模型打分（模型打分不稳定，也说不清为什么是这个分）。

每个维度从 100 分起扣：high −25、medium −12、low −5，扣到 0 为止。
扣分按经历条数归一化：经历写得多的简历被检查的地方也多，直接累加会让它天然吃亏（实测 7 条经历的简历
表达维度被扣到 0 分）。以 4 条经历为基准，超过的按比例摊薄，不足的不放大。
某个维度在本次诊断模式下没有任何来源能产生 finding（如只开 LLM 通道时的"量化"与"ATS"），
该维度记为 None 并退出加权——不能把"没人查"当成"没问题"记满分。

这是给用户看的展示分，不作为消融实验的指标（实验比较的是 F1、拦截率与成本）。
"""
from __future__ import annotations

from collections.abc import Iterable

from app.diagnose.types import CATEGORIES, Finding

PENALTY = {"high": 25, "medium": 12, "low": 5}
REFERENCE_UNITS = 4   # 归一化基准：这么多条经历以内不摊薄
# 初始权重，评测后再调；顺序与 CATEGORIES 一致
WEIGHTS = {"completeness": 0.25, "quantification": 0.25, "expression": 0.20, "consistency": 0.20, "ats": 0.10}

# 每种诊断模式下，哪些维度有来源
RULE_CATEGORIES = frozenset(CATEGORIES)
LLM_CATEGORIES = frozenset({"expression", "consistency"})
ACTIVE_CATEGORIES = {"rule_only": RULE_CATEGORIES, "llm_only": LLM_CATEGORIES, "hybrid": RULE_CATEGORIES}


def score(findings: Iterable[Finding], mode: str = "hybrid",
          unit_count: int = 0) -> tuple[float | None, dict[str, float | None]]:
    """返回 (总分, 各维度分)。只统计通过证据校验的 finding。unit_count 为经历条数，用于归一化。"""
    active = ACTIVE_CATEGORIES[mode]
    scale = REFERENCE_UNITS / max(unit_count, REFERENCE_UNITS)
    deducted = dict.fromkeys(CATEGORIES, 0)
    for f in findings:
        if f.verify_result != "failed":
            deducted[f.category] += PENALTY[f.severity]

    detail: dict[str, float | None] = {
        c: round(max(0.0, 100 - deducted[c] * scale), 1) if c in active else None for c in CATEGORIES}
    total_weight = sum(WEIGHTS[c] for c in active)
    if not total_weight:
        return None, detail
    overall = sum(WEIGHTS[c] * detail[c] for c in active) / total_weight
    return round(overall, 1), detail
