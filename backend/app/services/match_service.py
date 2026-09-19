"""匹配的建记录与落库。

匹配图（app/graphs）只做计算；这里负责建记录、判定是否过初筛、写 match_reports。
跑图由投递流水线（apply_service）负责，跑完调用这里的 save_result。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import CONFLICT, ApiError
from app.llm import prompts
from app.models import Diagnosis, Job, MatchReport, Resume

_IN_PROGRESS = ("pending", "running")
_REQUIREMENT_FIELDS = ("content", "req_type", "category", "weight", "skill")


def create_match(db: Session, resume: Resume, job: Job, mode: str, model: str | None) -> MatchReport:
    """建一条 pending 记录。同一份简历对同一个岗位同时只允许一个匹配在跑。"""
    running = db.scalar(select(MatchReport.id).where(
        MatchReport.resume_id == resume.id, MatchReport.job_id == job.id, MatchReport.status.in_(_IN_PROGRESS)))
    if running:
        raise ApiError(CONFLICT, "这份简历对该岗位的匹配正在进行，请稍候")
    report = MatchReport(resume_id=resume.id, job_id=job.id, mode=mode, model_name=model or settings.CHAT_MODEL,
                         prompt_version=prompts.MATCH_VERSION)
    db.add(report)
    db.commit()
    return report


def save_result(db: Session, report: MatchReport, job: Job, result: dict) -> None:
    """把匹配图的输出写进 match_reports。投递流水线（apply_service）也用它。"""
    requirements = {r["id"]: r for r in job.requirements or []}
    # 明细里带上要求项本身的内容：岗位之后被删掉，这份报告依然读得懂
    report.items = [{**{k: requirements[i.requirement_id].get(k) for k in _REQUIREMENT_FIELDS}, **i.to_dict()}
                    for i in result["items"]]
    overall = result["overall_match"]
    report.overall_match, report.dimension_scores = overall, result["dimension_scores"]
    report.passed = overall is not None and overall >= settings.SCREEN_THRESHOLD
    report.llm_item_count = result["llm_item_count"]
    report.hallucination_count = result["hallucination_count"]
    report.cost = result["cost"]
    # 未通过时要和匹配差距一起展示的诊断：投递流水线建记录时已经指定；单独匹配则取这份简历最近一次完成的
    report.diagnosis_id = report.diagnosis_id or db.scalar(
        select(Diagnosis.id).where(Diagnosis.resume_id == report.resume_id, Diagnosis.status.in_(("success", "partial")))
        .order_by(Diagnosis.id.desc()))
    report.status, report.finished_at = "success", datetime.now()
    db.commit()
