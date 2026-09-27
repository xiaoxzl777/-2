"""具体建议：结果页上点开一条问题 / 差距时现场生成（流式），生成过的存库，再打开直接用。

    简历问题  → findings.rewrite
    岗位差距  → match_reports.items[k].advice
两处存同一种结构：{text, violation_count, prompt_version, model, created_at}。text 是数字复检之后的全文。
生成失败不存，前端可以重试。拼 prompt 与复检在 app/rewrite/advice.py（领域层）。
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.errors import LLM_FAILED, NOT_FOUND, ApiError
from app.llm import prompts
from app.llm.client import LLMClient, LLMError
from app.models import Diagnosis, Finding, Job, MatchReport, Resume, User
from app.parser.pii import mask_pii
from app.rewrite.advice import AdvicePrompt, finding_prompt, fix_numbers, gap_prompt
from app.services.parse_service import SessionFactory

logger = logging.getLogger("app.advice")

TEMPERATURE = 0.3           # 写建议要有点变化，但不能发散（docs/04-design 4.1 改写建议同为 0.3）

Event = tuple[str, dict]     # ("delta", {text}) / ("done", 结果) / ("error", {code, message})


@dataclass(slots=True)
class AdviceTask:
    scene: str                              # 审计里的场景：rewrite = 简历问题，gap = 岗位差距
    ref: tuple[str, int]
    prompt: AdvicePrompt
    save: Callable[[Session, dict], None]   # 在新会话里把结果写回去


def _saved(advice: dict | None) -> dict | None:
    return advice if isinstance(advice, dict) and advice.get("text") else None


def _masked(resume: Resume) -> tuple[dict, str, str]:
    structure, full_text = resume.structure or {}, resume.full_text or ""
    return structure, full_text, mask_pii(full_text, name=(structure.get("basics") or {}).get("name"))


def finding_task(db: Session, user: User, finding_id: int) -> AdviceTask | dict:
    """返回待生成的任务；已经生成过就直接返回存下的结果。别人的、证据校验没通过（不展示）的都视同不存在。"""
    finding = db.get(Finding, finding_id)
    diagnosis = db.get(Diagnosis, finding.diagnosis_id) if finding else None
    resume = db.get(Resume, diagnosis.resume_id) if diagnosis else None
    if resume is None or resume.user_id != user.id or resume.is_deleted or finding.verify_result == "failed":
        raise ApiError(NOT_FOUND, "这条问题不存在")
    if saved := _saved(finding.rewrite):
        return saved

    structure, full_text, masked = _masked(resume)
    row = {"unit_id": finding.unit_id, "char_start": finding.char_start, "char_end": finding.char_end,
           "title": finding.title, "description": finding.description, "evidence_quote": finding.evidence_quote}

    def save(session: Session, result: dict) -> None:
        session.get(Finding, finding_id).rewrite = result

    return AdviceTask("rewrite", ("finding", finding_id),
                      finding_prompt(row, structure, full_text, masked, diagnosis.job_title), save)


def gap_task(db: Session, user: User, report_id: int, requirement_id: int) -> AdviceTask | dict:
    """岗位差距：只有没满足 / 部分满足的要求才有建议。"""
    report = db.get(MatchReport, report_id)
    resume = db.get(Resume, report.resume_id) if report else None
    if resume is None or resume.user_id != user.id or resume.is_deleted:
        raise ApiError(NOT_FOUND, "投递记录不存在")
    item = next((i for i in report.items or [] if i["requirement_id"] == requirement_id and i["status"] != "hit"), None)
    if item is None:
        raise ApiError(NOT_FOUND, "这条要求不存在，或者已经满足")
    if saved := _saved(item.get("advice")):
        return saved

    job = db.get(Job, report.job_id)
    requirement = next((r for r in (job.requirements if job else None) or [] if r["id"] == requirement_id), None)
    _, full_text, masked = _masked(resume)

    def save(session: Session, result: dict) -> None:
        row = session.get(MatchReport, report_id)
        # JSON 列要整体换一个新列表，改里面的字典 SQLAlchemy 察觉不到
        row.items = [{**i, "advice": result} if i["requirement_id"] == requirement_id else i for i in row.items or []]

    return AdviceTask("gap", ("match_report", report_id),
                      gap_prompt(item, requirement, full_text, masked, job.title if job else None), save)


def run(task: AdviceTask, llm: LLMClient, session_factory: SessionFactory) -> Iterator[Event]:
    """边生成边产出 delta；结束时做数字复检、存库，产出 done（以它的全文为准）。失败产出 error，什么都不存。"""
    text = ""
    try:
        for piece in llm.stream(task.scene, task.prompt.messages, prompt_version=prompts.ADVICE_VERSION,
                                ref=task.ref, temperature=TEMPERATURE):
            text += piece
            yield "delta", {"text": piece}
    except LLMError:
        logger.exception("生成建议失败 %s", task.ref)
        yield "error", {"code": LLM_FAILED, "message": "调用大模型失败，请稍后重试"}
        return
    if not text.strip():
        yield "error", {"code": LLM_FAILED, "message": "大模型没有返回内容，请稍后重试"}
        return

    final, violations = fix_numbers(text.strip(), task.prompt.checked_section, task.prompt.original)
    if violations:
        logger.info("建议里有 %d 个原文没有的数字，已换成占位符 %s", violations, task.ref)
    result = {"text": final, "violation_count": violations, "prompt_version": prompts.ADVICE_VERSION,
              "model": settings.CHAT_MODEL, "created_at": datetime.now().isoformat(timespec="seconds")}
    with session_factory() as db:          # 请求自己的会话在开始流式响应后就不能再用了
        task.save(db, result)
        db.commit()
    yield "done", result
