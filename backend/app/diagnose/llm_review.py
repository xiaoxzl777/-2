"""LLM 通道：对一个送审单元做语义审查，并核实模型给出的每一条证据。

一个单元内部的流程（最多 3 次模型调用）：
    调模型 ──► 输出不是合法 JSON？ ──是──► 带着错误原因重试
        │
        ▼ 逐条核实 evidence_quote（locate_span，只在本单元范围内找）
    全部能定位 ──► 结束
    有定位不到的 ──► 把这几条引用原样告诉模型，让它只重做这几条 ──► 再核实

首轮（attempt_no=1）定位失败的条数就是"被拦截的幻觉"，论文的拦截率指标由此而来；
重试产出的条目只影响最终展示，不参与该指标的分子分母。

领域层：不碰数据库；模型调用经注入的 LLMClient。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.diagnose.evidence import locate_span
from app.diagnose.types import Finding, ReviewUnit
from app.llm import prompts
from app.llm.client import LLMClient

MAX_ATTEMPTS = 3            # 首次 + 最多 2 次重试
MAX_FINDINGS_PER_UNIT = 3

# risk_type → 评分维度
CATEGORY_OF = {"depth_mismatch": "expression", "vague": "expression", "exaggeration": "expression",
               "unclear_ownership": "consistency", "incoherent": "consistency"}
_TITLES = {"depth_mismatch": "技术深度与声明不匹配", "vague": "表述模糊", "exaggeration": "有夸大嫌疑",
           "unclear_ownership": "职责边界不清", "incoherent": "逻辑不连贯"}


class _LLMFinding(BaseModel):
    risk_type: Literal["depth_mismatch", "vague", "exaggeration", "unclear_ownership", "incoherent"]
    severity: Literal["high", "medium", "low"]
    evidence_quote: str
    reason: str
    suggestion: str = ""


class _ReviewOut(BaseModel):
    findings: list[_LLMFinding] = Field(default_factory=list)


@dataclass(slots=True)
class UnitReview:
    verified: list[Finding] = field(default_factory=list)
    rejected: list[Finding] = field(default_factory=list)   # 证据定位不到的，verify_result='failed'
    schema_errors: int = 0
    cost: float = 0.0


def _to_finding(item: _LLMFinding, unit: ReviewUnit, attempt: int, full_text: str, masked_text: str) -> Finding:
    """核实一条模型给出的问题。定位成功则证据改用原文切片（模型看到的是掩码文本）。"""
    base = dict(source="llm", risk_type=item.risk_type, category=CATEGORY_OF[item.risk_type], severity=item.severity,
                title=_TITLES[item.risk_type], description=item.reason, suggestion=item.suggestion,
                unit_id=unit.unit_id, attempt_no=attempt)
    where = locate_span(item.evidence_quote, masked_text, hint=(unit.char_start, unit.char_end))
    inside_unit = where is not None and unit.char_start <= where.start and where.end <= unit.char_end
    if not inside_unit:  # 定位不到，或定位到了别的经历里——都不能作为这条经历的证据
        return Finding(**base, evidence_quote=item.evidence_quote, verify_result="failed",
                       match_score=where.score if where else 0.0)
    return Finding(**base, evidence_quote=full_text[where.start:where.end], char_start=where.start,
                   char_end=where.end, verify_result=where.method, match_score=where.score)


def _same_problem(a: Finding, b: Finding) -> bool:
    """同一类型、且指向同一处，才算重复。同一句话可以同时有"模糊"和"职责不清"两个问题。"""
    return a.risk_type == b.risk_type and a.char_start < b.char_end and b.char_start < a.char_end


def review_unit(unit: ReviewUnit, full_text: str, masked_text: str, llm: LLMClient, *,
                job_title: str | None = None, rule_summary: str = "", model: str | None = None,
                ref: tuple[str, int] | None = None) -> UnitReview:
    user = prompts.DIAGNOSE_USER.format(
        job_title=job_title or "未指定", entry_name=unit.entry_name or "（自我评价）",
        text=masked_text[unit.char_start:unit.char_end], rule_summary=rule_summary or "无")
    messages = [("system", prompts.DIAGNOSE_SYSTEM), ("user", user)]
    review = UnitReview()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        result = llm.invoke("diagnose", messages, prompt_version=prompts.DIAGNOSE_VERSION,
                            schema=_ReviewOut, ref=ref, model=model)
        review.cost += result.cost

        if result.parsed is None:
            review.schema_errors += 1
            feedback = prompts.DIAGNOSE_RETRY_SCHEMA.format(error=result.parse_error)
        else:
            failed_now = []
            for item in result.parsed.findings[:MAX_FINDINGS_PER_UNIT]:
                finding = _to_finding(item, unit, attempt, full_text, masked_text)
                if finding.verify_result == "failed":
                    review.rejected.append(finding)
                    failed_now.append(finding)
                elif not any(_same_problem(finding, kept) for kept in review.verified):  # 重试时模型可能把已通过的又报一遍
                    review.verified.append(finding)
            if not failed_now:
                break
            quotes = "\n".join(f"- {f.evidence_quote}" for f in failed_now)
            feedback = prompts.DIAGNOSE_RETRY_EVIDENCE.format(failed_quotes=quotes)

        messages = [*messages, ("assistant", result.text[:2000]), ("user", feedback)]
    return review
