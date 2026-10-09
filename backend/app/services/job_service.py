"""岗位：保存用户粘贴的 JD，并同步解析成要求项。

解析只有一次模型调用（约 2–4 秒），所以放在请求里同步做：返回时要求项已就绪，
后面的投递流水线（图 A）不必再处理"岗位还没解析完"这种状态。解析失败则整条不保存，用户改完重新提交即可。
"""
from __future__ import annotations

import logging

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domains import DEFAULT, DOMAINS
from app.errors import BAD_REQUEST, LLM_FAILED, NOT_FOUND, ApiError
from app.llm.client import LLM_DOWN, LLMClient, LLMError
from app.matching.jd_parser import parse_jd
from app.models import Job, User
from app.parser.extract import clean_text
from app.services.skill_service import load_skill_dict

logger = logging.getLogger("app.job")


def normalize_jd(raw_text: str) -> str:
    """要求项的 char 区间相对这份文本，所以只在保存前清洗这一次：逐行去首尾空白与控制字符，去掉首尾空行。"""
    return "\n".join(clean_text(line) for line in raw_text.splitlines()).strip("\n")


def create_job(db: Session, user: User, title: str, company: str | None, raw_text: str, llm: LLMClient,
               domain: str = DEFAULT.key) -> Job:
    if domain not in DOMAINS:
        raise ApiError(BAD_REQUEST, f"未知的求职方向：{domain}（可用：{'、'.join(DOMAINS)}）")
    job = Job(user_id=user.id, title=title.strip(), company=(company or "").strip() or None, domain=domain,
              raw_text=normalize_jd(raw_text))
    db.add(job)
    db.flush()                                        # 先拿到 id，模型调用的审计记录要引用它
    try:
        result = parse_jd(job.title, job.raw_text, llm, load_skill_dict(db), ref=("job", job.id),
                          domain=DOMAINS[domain])
    except LLMError as e:
        db.rollback()
        raise ApiError(LLM_FAILED, LLM_DOWN if e.unavailable else "调用大模型解析岗位失败，请稍后重试") from e
    if result.error:
        db.rollback()
        raise ApiError(LLM_FAILED, "大模型返回的结果无法使用，请稍后重试")
    if not result.requirements:
        db.rollback()
        raise ApiError(BAD_REQUEST, "没能从这段文字里识别出岗位要求，请确认粘贴的是完整的岗位描述")

    if result.rejected:
        logger.info("JD 解析丢弃了 %d 条无法在原文中定位的要求 job_id=%s", result.rejected, job.id)
    job.requirements, job.parse_status = result.requirements, "success"
    db.commit()
    return job


def list_jobs(db: Session, user: User, include_templates: bool) -> list[Job]:
    """我的岗位（新的在前）；include_templates 时内置模板排在后面，按 seed.sql 里的先后（id 从小到大）。"""
    owner = Job.user_id == user.id
    if include_templates:
        owner = or_(owner, Job.is_template.is_(True))
    jobs = list(db.scalars(select(Job).where(owner, Job.is_deleted.is_(False)).order_by(Job.id.desc())))
    return [j for j in jobs if not j.is_template] + [j for j in reversed(jobs) if j.is_template]


def get_visible_job(db: Session, user: User, job_id: int) -> Job:
    """自己的岗位或内置模板。别人的、已删除的一律视同不存在。匹配、投递、面试接口都经这里取岗位。"""
    job = db.get(Job, job_id)
    if job is None or job.is_deleted or not (job.is_template or job.user_id == user.id):
        raise ApiError(NOT_FOUND, "岗位不存在")
    return job


def delete_job(db: Session, user: User, job_id: int) -> None:
    job = get_visible_job(db, user, job_id)
    if job.user_id != user.id:                        # 内置模板不能删
        raise ApiError(NOT_FOUND, "岗位不存在")
    job.is_deleted = True
    db.commit()
