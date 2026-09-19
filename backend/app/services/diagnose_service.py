"""诊断任务：跑诊断图，把结果落库。

图（app/graphs）只做计算；这里负责读简历、改状态、把 finding 映射到页码与坐标、统计指标、写数据库。
诊断只读取解析阶段产出的 full_text / structure，从不修改它们（系统不变量③）。
"""
from __future__ import annotations

import logging
from bisect import bisect_right
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.diagnose.types import Finding as DomainFinding
from app.errors import CONFLICT, ApiError
from app.graphs.diagnose_graph import build_diagnose_graph, initial_state
from app.llm import prompts
from app.llm.client import LLMClient
from app.models import Diagnosis, Finding, LlmCall, ParsedBlock, Resume
from app.parser.pii import mask_pii
from app.services.parse_service import SessionFactory

logger = logging.getLogger("app.diagnose")

_IN_PROGRESS = ("pending", "running")


def create_diagnosis(db: Session, resume: Resume, mode: str, model: str | None, job_title: str | None) -> Diagnosis:
    """建一条 pending 记录。同一份简历同时只允许一个诊断在跑。"""
    running = db.scalar(select(Diagnosis.id).where(Diagnosis.resume_id == resume.id, Diagnosis.status.in_(_IN_PROGRESS)))
    if running:
        raise ApiError(CONFLICT, "这份简历已有诊断正在进行，请稍候")
    diagnosis = Diagnosis(resume_id=resume.id, mode=mode, model_name=model or settings.CHAT_MODEL,
                          prompt_version=prompts.DIAGNOSE_VERSION, job_title=job_title)
    db.add(diagnosis)
    db.commit()
    return diagnosis


def run_diagnosis(diagnosis_id: int, session_factory: SessionFactory, llm: LLMClient) -> None:
    """BackgroundTasks 入口。"""
    with session_factory() as db:
        diagnosis = db.get(Diagnosis, diagnosis_id)
        if diagnosis is None:
            return
        resume = db.get(Resume, diagnosis.resume_id)
        diagnosis.status, diagnosis.started_at = "running", datetime.now()
        db.commit()

        try:
            state = initial_state(
                structure=resume.structure or {}, full_text=resume.full_text or "",
                masked_text=mask_pii(resume.full_text or "", name=(resume.structure or {}).get("basics", {}).get("name")),
                mode=diagnosis.mode, model=diagnosis.model_name, job_title=diagnosis.job_title,
                ats_signals=resume.ats_signals, page_count=resume.page_count, diagnosis_id=diagnosis.id)
            result = build_diagnose_graph(llm).invoke(state)
        except Exception as e:  # noqa: BLE001 —— 后台任务必须落成失败状态，不能把异常抛丢
            logger.exception("诊断失败 diagnosis_id=%s", diagnosis_id)
            db.rollback()
            diagnosis.status, diagnosis.error_msg = "failed", f"{type(e).__name__}: {e}"[:200]
            diagnosis.finished_at = datetime.now()
            db.commit()
            return
        _save_result(db, diagnosis, resume, result)


def _save_result(db: Session, diagnosis: Diagnosis, resume: Resume, result: dict) -> None:
    locate = _BlockLocator(db, resume.id)
    shown: list[DomainFinding] = result["findings"]            # 合并去重后展示给用户的
    rejected: list[DomainFinding] = result["rejected_findings"]  # 证据定位失败的：不展示，但评测要统计
    for f in [*shown, *rejected]:
        page_no, bbox = locate(f.char_start)
        db.add(Finding(diagnosis_id=diagnosis.id, page_no=page_no, bbox=bbox, **f.to_dict()))

    first_round = [f for f in [*result["llm_findings"], *rejected] if f.attempt_no == 1]
    diagnosis.units_total = result["units_total"]
    diagnosis.units_skipped = result["units_skipped"]
    diagnosis.rule_finding_count = len(result["rule_findings"])
    diagnosis.llm_finding_count = len(first_round)
    diagnosis.hallucination_count = sum(1 for f in first_round if f.verify_result == "failed")
    diagnosis.schema_error_count = result["schema_errors"]
    diagnosis.overall_score, diagnosis.score_detail = result["overall_score"], result["score_detail"]
    diagnosis.cost = result["cost"]
    tokens = db.execute(select(func.coalesce(func.sum(LlmCall.token_input), 0), func.coalesce(func.sum(LlmCall.token_output), 0))
                        .where(LlmCall.ref_type == "diagnosis", LlmCall.ref_id == diagnosis.id)).one()
    diagnosis.token_input, diagnosis.token_output = int(tokens[0]), int(tokens[1])
    # 成本预检截掉了部分单元 → partial：结果可用，但不完整
    diagnosis.status = "partial" if result["units_skipped"] else "success"
    diagnosis.finished_at = datetime.now()
    resume.overall_score = result["overall_score"]             # 与状态同一事务回写，列表页直接可用
    db.commit()


class _BlockLocator:
    """字符位置 → (页码, 块的 bbox)。一次查出全部块，之后二分查找。"""

    def __init__(self, db: Session, resume_id: int):
        self._blocks = db.scalars(
            select(ParsedBlock).where(ParsedBlock.resume_id == resume_id).order_by(ParsedBlock.char_start)).all()
        self._starts = [b.char_start for b in self._blocks]

    def __call__(self, char_start: int | None) -> tuple[int | None, list[float] | None]:
        if char_start is None or not self._blocks:
            return None, None
        block = self._blocks[max(0, bisect_right(self._starts, char_start) - 1)]
        has_bbox = None not in (block.x0, block.y0, block.x1, block.y1)
        return block.page_no, [block.x0, block.y0, block.x1, block.y1] if has_bbox else None


def latest_diagnosis(db: Session, resume_id: int, diagnosis_id: int | None = None) -> Diagnosis | None:
    """指定了 id 就取那一条；否则取最近一条已完成的，没有则取最近一条（可能还在跑）。"""
    base = select(Diagnosis).where(Diagnosis.resume_id == resume_id)
    if diagnosis_id is not None:
        return db.scalar(base.where(Diagnosis.id == diagnosis_id))
    finished = db.scalar(base.where(Diagnosis.status.in_(("success", "partial"))).order_by(Diagnosis.id.desc()))
    return finished or db.scalar(base.order_by(Diagnosis.id.desc()))


def visible_findings(db: Session, diagnosis_id: int) -> list[Finding]:
    """展示给用户的 finding：不含证据定位失败的。严重的在前，同级按在原文中的位置。"""
    rows = db.scalars(select(Finding).where(Finding.diagnosis_id == diagnosis_id, Finding.verify_result != "failed")).all()
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(rows, key=lambda f: (order[f.severity], f.char_start if f.char_start is not None else 1 << 30))
