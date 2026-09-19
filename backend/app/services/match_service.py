"""匹配任务：准备检索索引，跑匹配图，把结果落库。

图（app/graphs/match_graph.py）只做计算；这里负责读简历与岗位、保证这份简历的检索单元已入库、
把"按要求文本检索"包成一个函数注入给图、判定是否过初筛、写 match_reports。
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import CONFLICT, ApiError
from app.graphs.match_graph import build_match_graph, initial_state
from app.llm import prompts
from app.llm.client import LLMClient
from app.matching.units import build_match_units
from app.models import Diagnosis, Job, MatchReport, Resume
from app.parser.pii import mask_pii
from app.retrieval.unit_store import ResumeUnitStore
from app.services.parse_service import SessionFactory

logger = logging.getLogger("app.match")

_IN_PROGRESS = ("pending", "running")
_USES_RETRIEVAL = ("llm_rag", "hybrid")
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


def run_match(report_id: int, session_factory: SessionFactory, llm: LLMClient, store: ResumeUnitStore) -> None:
    """BackgroundTasks 入口。"""
    with session_factory() as db:
        report = db.get(MatchReport, report_id)
        if report is None:
            return
        resume, job = db.get(Resume, report.resume_id), db.get(Job, report.job_id)
        report.status, report.started_at = "running", datetime.now()
        db.commit()

        try:
            result = _run_graph(report, resume, job, llm, store)
        except Exception as e:  # noqa: BLE001 —— 后台任务必须落成失败状态，不能把异常抛丢
            logger.exception("匹配失败 match_report_id=%s", report_id)
            db.rollback()
            report.status, report.error_msg = "failed", f"{type(e).__name__}: {e}"[:200]
            report.finished_at = datetime.now()
            db.commit()
            return
        save_result(db, report, job, result)


def _run_graph(report: MatchReport, resume: Resume, job: Job, llm: LLMClient, store: ResumeUnitStore) -> dict:
    structure, full_text = resume.structure or {}, resume.full_text or ""
    masked_text = mask_pii(full_text, name=structure.get("basics", {}).get("name"))

    retrieve = make_retriever(report, resume, masked_text, store)
    state = initial_state(requirements=job.requirements or [], structure=structure, full_text=full_text,
                          masked_text=masked_text, mode=report.mode, model=report.model_name, match_report_id=report.id)
    return build_match_graph(llm, retrieve).invoke(state)


def make_retriever(report: MatchReport, resume: Resume, masked_text: str, store: ResumeUnitStore):
    """用到检索的 mode：保证这份简历的单元已入库，返回"要求文本 → 候选单元"的函数；其余 mode 返回 None。"""
    if report.mode not in _USES_RETRIEVAL:
        return None
    units = build_match_units(resume.structure or {}, resume.sections or [], resume.full_text or "")
    store.ensure_indexed(resume.id, units, masked_text)           # 首次匹配、或结构被纠正过 → （重新）入库
    resume_id, ref = resume.id, ("match_report", report.id)

    def retrieve(query: str):
        return store.retrieve(resume_id, query, recall_k=settings.MATCH_RECALL_K, top_k=settings.RAG_TOP_K, ref=ref)

    return retrieve


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
