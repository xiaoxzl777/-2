"""求职方向：工作台第一步的下拉框从这里取选项，加一个方向前端不用改。"""
from __future__ import annotations

from fastapi import APIRouter

from app.domains import DOMAINS
from app.schemas import ApiResponse, DomainOut, ok

router = APIRouter(prefix="/domains", tags=["domains"])


@router.get("", response_model=ApiResponse[list[DomainOut]])
def list_domains():
    """不用登录：只是静态配置（app/domains）。顺序就是下拉框里的顺序。"""
    return ok([DomainOut(key=d.key, name=d.name, icon=d.icon, desc=d.desc, rule_hint=d.rule_hint,
                         interview_hint=d.interview_hint, interview_label=d.interview_label,
                         interviewer=d.texts["interviewer"], sample_jd=d.sample_jd) for d in DOMAINS.values()])
