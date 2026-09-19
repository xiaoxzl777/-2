"""诊断结果查询。诊断本身由投递（POST /apply）触发，不单独提供触发接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_owned_resume
from app.errors import NOT_FOUND, ApiError
from app.models import Diagnosis, Resume
from app.schemas import ApiResponse, DiagnosisOut, DiagnosisStats, FindingOut, ok
from app.services import diagnose_service

router = APIRouter(prefix="/resumes", tags=["diagnose"])


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
