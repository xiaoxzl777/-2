"""投递：一次把"诊断 + 匹配 + 初筛"跑完（图 A），并沿途推送进度。

一次投递 = 一条 diagnoses 记录 + 一条 match_reports 记录（后者的 diagnosis_id 指向前者），
投递的 id 就用 match_report 的 id。落库复用诊断 / 匹配各自 service 的 save_result，这里只做编排。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

from sqlalchemy.orm import Session

from app.cache.pubsub import Publish
from app.errors import ApiError
from app.graphs.apply_graph import build_apply_graph
from app.llm.client import LLMClient
from app.models import Diagnosis, Finding, Job, MatchReport, Resume
from app.parser.pii import mask_pii
from app.retrieval.unit_store import ResumeUnitStore
from app.services import diagnose_service, match_service
from app.services.parse_service import SessionFactory

logger = logging.getLogger("app.apply")

PARSE_WAIT_SECONDS = 120        # 刚上传就点了投递：等后台解析完成的最长时间
MAX_RESUME_ISSUES = 8           # 未通过说明里最多列几条简历自身的问题
# 图 A 每完成一个节点推一次进度
_PROGRESS = {"diagnose": (60, "简历诊断完成"), "match": (85, "岗位匹配完成"), "gate": (95, "初筛判定完成")}


def create_apply(db: Session, resume: Resume, job: Job, diagnose_mode: str, match_mode: str,
                 model: str | None) -> MatchReport:
    report = match_service.create_match(db, resume, job, match_mode, model)          # 同一对简历-岗位在跑 → 409
    try:
        diagnosis = diagnose_service.create_diagnosis(db, resume, diagnose_mode, model, job.title)   # 简历在诊断中 → 409
    except ApiError:
        db.delete(report)
        db.commit()
        raise
    report.diagnosis_id = diagnosis.id
    db.commit()
    return report


def run_apply(report_id: int, session_factory: SessionFactory, llm: LLMClient, store: ResumeUnitStore,
              publish: Publish) -> None:
    """BackgroundTasks 入口。"""
    task_id = f"apply:{report_id}"
    with session_factory() as db:
        report = db.get(MatchReport, report_id)
        if report is None:
            return
        diagnosis = db.get(Diagnosis, report.diagnosis_id)
        resume, job = db.get(Resume, report.resume_id), db.get(Job, report.job_id)
        try:
            publish(task_id, "progress", {"stage": "parsing", "percent": 5, "message": "正在解析简历"})
            _wait_until_parsed(db, resume)
            now = datetime.now()
            report.status = diagnosis.status = "running"
            report.started_at = diagnosis.started_at = now
            db.commit()

            publish(task_id, "progress", {"stage": "analyzing", "percent": 20, "message": "正在诊断简历并对照岗位要求"})
            result = _run_graph(task_id, report, diagnosis, resume, job, llm, store, publish)
        except Exception as e:  # noqa: BLE001 —— 后台任务必须落成失败状态，不能把异常抛丢
            logger.exception("投递失败 match_report_id=%s", report_id)
            db.rollback()
            message = f"{type(e).__name__}: {e}"[:200]
            for row in (report, diagnosis):
                row.status, row.error_msg, row.finished_at = "failed", message, datetime.now()
            db.commit()
            publish(task_id, "error", {"message": "分析失败，请稍后重试"})
            return

        diagnose_service.save_result(db, diagnosis, resume, result["diagnosis"])
        match_service.save_result(db, report, job, result["match"])
        publish(task_id, "done", {"id": report.id, "status": report.status, "passed": result["passed"]})


def _wait_until_parsed(db: Session, resume: Resume) -> None:
    deadline = time.monotonic() + PARSE_WAIT_SECONDS
    while resume.parse_status in ("pending", "parsing"):
        if time.monotonic() > deadline:
            raise TimeoutError("等待简历解析超时")
        time.sleep(0.5)
        # 先结束当前事务再重读：MySQL 默认 REPEATABLE READ，同一事务里无论 refresh 多少次，
        # 读到的都是事务开始时的快照，永远看不到解析任务后来提交的状态
        db.commit()
        db.refresh(resume)
    if resume.parse_status != "success":
        raise RuntimeError(f"简历解析失败：{resume.parse_error}")


def _run_graph(task_id: str, report: MatchReport, diagnosis: Diagnosis, resume: Resume, job: Job,
               llm: LLMClient, store: ResumeUnitStore, publish: Publish) -> dict:
    structure, full_text = resume.structure or {}, resume.full_text or ""
    masked_text = mask_pii(full_text, name=structure.get("basics", {}).get("name"))
    state = {
        "diagnosis_id": diagnosis.id, "match_report_id": report.id, "diagnose_mode": diagnosis.mode,
        "match_mode": report.mode, "model": report.model_name, "job_title": job.title,
        "requirements": job.requirements or [], "structure": structure, "full_text": full_text,
        "masked_text": masked_text, "ats_signals": resume.ats_signals, "page_count": resume.page_count,
    }
    graph = build_apply_graph(llm, match_service.make_retriever(report, resume, masked_text, store))

    result: dict = {}
    for update in graph.stream(state, stream_mode="updates"):       # 每完成一个节点吐一次：{节点名: 它写回的字段}
        for node, fields in update.items():
            result.update(fields)
            percent, message = _PROGRESS[node]
            publish(task_id, "progress", {"stage": node, "percent": percent, "message": message})
    return result


# ───────────── 读取 ─────────────


def stage_of(report: MatchReport, resume: Resume) -> str:
    """给轮询的前端一个粗粒度的阶段（SSE 连不上时用）。"""
    if report.status == "pending":
        return "parsing" if resume.parse_status != "success" else "queued"
    return {"running": "analyzing", "success": "done", "failed": "failed"}[report.status]


def gap_items(report: MatchReport) -> list[dict]:
    """对照岗位的差距：没满足与部分满足的要求。越重要的越靠前，同等重要时完全没满足的在前。"""
    gaps = [i for i in report.items or [] if i["status"] != "hit"]
    return sorted(gaps, key=lambda i: (-i["weight"], i["status"] != "miss", i["requirement_id"]))


def resume_issues(db: Session, report: MatchReport) -> list[Finding]:
    """简历自身最值得先改的几个问题（诊断结果里最严重的）。"""
    if report.diagnosis_id is None:
        return []
    return diagnose_service.visible_findings(db, report.diagnosis_id)[:MAX_RESUME_ISSUES]
