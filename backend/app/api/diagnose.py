"""诊断：触发与查询。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db, get_session_factory
from app.deps import get_owned_resume, get_parsed_resume
from app.errors import BAD_REQUEST, NOT_FOUND, ApiError
from app.llm.client import LLMClient, get_llm_client
from app.llm.registry import MODEL_REGISTRY
from app.models import Diagnosis, Resume
from app.schemas import ApiResponse, DiagnoseIn, DiagnosisOut, DiagnosisStats, FindingOut, TaskOut, ok
from app.services import diagnose_service
from app.services.parse_service import SessionFactory

router = APIRouter(prefix="/resumes", tags=["diagnose"])


@router.post("/{resume_id}/diagnose", response_model=ApiResponse[TaskOut])
def start_diagnosis(
    background: BackgroundTasks,
    body: DiagnoseIn | None = None,
    resume: Resume = Depends(get_parsed_resume),
    db: Session = Depends(get_db),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm: LLMClient = Depends(get_llm_client),
):
    """触发一次诊断（后台执行）。轮询 GET /resumes/{id}/diagnosis?diagnosis_id= 查看进度与结果。"""
    body = body or DiagnoseIn()
    if body.model is not None and body.model not in MODEL_REGISTRY:
        raise ApiError(BAD_REQUEST, f"未知的模型：{body.model}（可用：{sorted(MODEL_REGISTRY)}）")

    diagnosis = diagnose_service.create_diagnosis(db, resume, body.mode, body.model, body.job_title)
    background.add_task(diagnose_service.run_diagnosis, diagnosis.id, session_factory, llm)
    return ok(TaskOut(id=diagnosis.id, task_id=f"diagnose:{diagnosis.id}", status=diagnosis.status))


@router.get("/{resume_id}/diagnosis", response_model=ApiResponse[DiagnosisOut])
def get_diagnosis(
    diagnosis_id: int | None = Query(default=None),
    resume: Resume = Depends(get_owned_resume),
    db: Session = Depends(get_db),
):
    """不带 diagnosis_id：最近一次已完成的诊断（没有则返回最近一次，可能还在进行）。"""
    diagnosis = diagnose_service.latest_diagnosis(db, resume.id, diagnosis_id)
    if diagnosis is None:
        raise ApiError(NOT_FOUND, "这份简历还没有诊断记录")
    findings = diagnose_service.visible_findings(db, diagnosis.id)
    return ok(_diagnosis_out(diagnosis, [FindingOut.model_validate(f) for f in findings]))


def _diagnosis_out(d: Diagnosis, findings: list[FindingOut]) -> DiagnosisOut:
    rate = round(d.hallucination_count / d.llm_finding_count, 3) if d.llm_finding_count else None
    return DiagnosisOut(
        id=d.id, status=d.status, error_msg=d.error_msg, mode=d.mode, model_name=d.model_name,
        prompt_version=d.prompt_version, job_title=d.job_title,
        overall_score=float(d.overall_score) if d.overall_score is not None else None, score_detail=d.score_detail,
        stats=DiagnosisStats(
            units_total=d.units_total, units_skipped=d.units_skipped, rule_finding_count=d.rule_finding_count,
            llm_finding_count=d.llm_finding_count, hallucination_count=d.hallucination_count,
            intercept_rate=rate, schema_error_count=d.schema_error_count),
        cost=float(d.cost), token_input=d.token_input, token_output=d.token_output,
        started_at=d.started_at, finished_at=d.finished_at, findings=findings,
    )
