"""ORM 模型：11 张表，与 docs/02-database.md 一一对应。

约定：
- 所有 char_start / char_end 都是相对 resumes.full_text 的偏移，开区间 [start, end)。
- JSON 字段只整体读写，不做条件查询；结构见 docs/02-database.md。
- 枚举用 native_enum 存为 MySQL ENUM，取值直接写字符串，不另建 Python Enum 类。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CHAR,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy import text as sql_text  # 别名：ParsedBlock 有名为 text 的列，会遮住函数
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# MySQL 下为 MEDIUMTEXT（16MB），其他方言（测试用 SQLite）退化为 Text
LongText = Text().with_variant(MEDIUMTEXT(), "mysql")
# 主键：MySQL 用 BIGINT；SQLite 只有 INTEGER 主键才自增
PK = BigInteger().with_variant(Integer(), "sqlite")


class Base(DeclarativeBase):
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


# 仅 MySQL 支持、且 SQLAlchemy 不会自动生成的 DDL；由 dump_schema.py 追加到 sql/schema.sql 末尾。
# 语句必须幂等（MODIFY 重复执行无副作用）。
MYSQL_POST_DDL: list[str] = [
    # 数据库层自动刷新 updated_at：原生 SQL 的 UPDATE（如启动清理）也能正确更新
    "ALTER TABLE resumes MODIFY updated_at DATETIME NOT NULL "
    "DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
]


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime, nullable=False, server_default=func.now())


# ① ─────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("seeker", "admin", name="user_role"), nullable=False, server_default="seeker"
    )
    created_at: Mapped[datetime] = _created_at()

    resumes: Mapped[list[Resume]] = relationship(back_populates="user")


# ② ─────────────────────────────────────────────────────────────
class Resume(Base):
    __tablename__ = "resumes"
    __table_args__ = (
        Index("idx_user", "user_id", "is_deleted", "updated_at"),
        Index("idx_hash", "user_id", "file_hash"),
        Base.__table_args__,
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), comment="版本链，本期恒为 NULL"
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="原始文件名消毒后，仅展示")

    # 文件
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="相对路径 uploads/{user_id}/{uuid}.{ext}")
    file_type: Mapped[str] = mapped_column(Enum("pdf", "docx", name="file_type"), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, comment="SHA-256")

    # 解析状态与版面
    parse_status: Mapped[str] = mapped_column(
        Enum("pending", "parsing", "success", "failed", name="parse_status"),
        nullable=False,
        server_default="pending",
    )
    parse_error: Mapped[str | None] = mapped_column(String(100), comment="scanned_pdf / interrupted / exception:<msg>")
    layout_type: Mapped[str] = mapped_column(
        Enum("single", "double", "sidebar", "table", "unknown", name="layout_type"),
        nullable=False,
        server_default="unknown",
        comment="第 1 页判定；DOCX 恒 single",
    )
    layout_confidence: Mapped[float | None] = mapped_column(Float, comment="各页最小值；<0.7 触发 LLM 兜底")
    layout_detail: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, comment="[{page_no, layout_type, confidence, gap}]"
    )
    used_llm_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("0"))
    page_count: Mapped[int | None] = mapped_column(Integer, comment="DOCX 为 NULL")
    ats_signals: Mapped[dict[str, Any] | None] = mapped_column(JSON, comment="{textboxes, drawings, images}")

    # 内容
    full_text: Mapped[str | None] = mapped_column(LongText, comment="坐标系基准，解析后永不改变")
    structure: Mapped[dict[str, Any] | None] = mapped_column(JSON, comment="结构化结果，含 summary / skill_mentions")
    sections: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, comment="[{type, title, char_start, char_end, confidence}]"
    )
    is_corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("0"))
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime)

    overall_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="最近一次成功诊断，同事务回写")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("0"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="resumes")
    blocks: Mapped[list[ParsedBlock]] = relationship(
        back_populates="resume", cascade="all, delete-orphan", order_by="ParsedBlock.block_index"
    )
    diagnoses: Mapped[list[Diagnosis]] = relationship(back_populates="resume", cascade="all, delete-orphan")


# ③ ─────────────────────────────────────────────────────────────
class ParsedBlock(Base):
    __tablename__ = "parsed_blocks"
    __table_args__ = (
        Index("idx_order", "resume_id", "block_index"),
        Index("idx_char", "resume_id", "char_start"),
        Base.__table_args__,
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    block_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="重建后的全局阅读顺序")
    page_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    column_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="0=左栏/单栏 1=右栏 -1=跨栏行"
    )

    # DOCX 无版面信息时为 NULL
    x0: Mapped[float | None] = mapped_column(Float)
    y0: Mapped[float | None] = mapped_column(Float)
    x1: Mapped[float | None] = mapped_column(Float)
    y1: Mapped[float | None] = mapped_column(Float)

    text: Mapped[str] = mapped_column(Text, nullable=False)
    font_size: Mapped[float | None] = mapped_column(Float)
    is_bold: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("0"))

    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)

    resume: Mapped[Resume] = relationship(back_populates="blocks")


# ④ ─────────────────────────────────────────────────────────────
class Diagnosis(Base):
    __tablename__ = "diagnoses"
    __table_args__ = (Index("idx_resume", "resume_id", "created_at"), Base.__table_args__)

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)

    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "success", "partial", "failed", "cancelled", name="diagnosis_status"),
        nullable=False,
        server_default="pending",
        comment="partial = 成本预检截断了部分条目",
    )
    error_msg: Mapped[str | None] = mapped_column(String(200))

    # 实验参数
    mode: Mapped[str] = mapped_column(
        Enum("rule_only", "llm_only", "hybrid", name="diagnose_mode"), nullable=False, server_default="hybrid"
    )
    model_name: Mapped[str | None] = mapped_column(String(50))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    job_title: Mapped[str | None] = mapped_column(String(200))

    # 结果统计（只统计首轮 attempt_no=1）
    units_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    units_skipped: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rule_finding_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    llm_finding_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    hallucination_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    schema_error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    overall_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    score_detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    token_input: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    token_output: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, server_default="0")

    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created_at()

    resume: Mapped[Resume] = relationship(back_populates="diagnoses")
    findings: Mapped[list[Finding]] = relationship(back_populates="diagnosis", cascade="all, delete-orphan")


# ⑤ ─────────────────────────────────────────────────────────────
class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        Index("idx_diagnosis", "diagnosis_id", "severity"),
        Index("idx_verify", "diagnosis_id", "verify_result"),
        Base.__table_args__,
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    diagnosis_id: Mapped[int] = mapped_column(ForeignKey("diagnoses.id", ondelete="CASCADE"), nullable=False)

    source: Mapped[str] = mapped_column(Enum("rule", "llm", name="finding_source"), nullable=False)
    rule_code: Mapped[str | None] = mapped_column(String(50), comment="规则通道")
    risk_type: Mapped[str | None] = mapped_column(String(50), comment="LLM 通道")
    category: Mapped[str] = mapped_column(
        Enum("completeness", "quantification", "expression", "consistency", "ats", name="finding_category"),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(Enum("high", "medium", "low", name="severity"), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    suggestion: Mapped[str | None] = mapped_column(Text)

    # 溯源定位
    unit_id: Mapped[str | None] = mapped_column(String(40), comment="如 work[0].highlights[2]")
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    page_no: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list[float] | None] = mapped_column(JSON, comment="落库时由 parsed_blocks 映射；DOCX 为 NULL")

    # 校验状态：failed 行保留不展示，评测统计要用
    verify_result: Mapped[str] = mapped_column(Enum("exact", "fuzzy", "failed", name="verify_result"), nullable=False)
    match_score: Mapped[float | None] = mapped_column(Float)
    attempt_no: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")

    rewrite: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment="{used_rag, used_rerank, rewritten, placeholders, changes, violation_count, created_at}"
    )
    created_at: Mapped[datetime] = _created_at()

    diagnosis: Mapped[Diagnosis] = relationship(back_populates="findings")


# ⑥ ─────────────────────────────────────────────────────────────
class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("idx_job_user", "user_id", "is_deleted"),
        Index("idx_template", "is_template"),
        Base.__table_args__,
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), comment="模板岗位为 NULL")
    is_template: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("0"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200))
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    requirements: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, comment="[{id, req_type, category, content, skill_id, weight}]"
    )
    parse_status: Mapped[str] = mapped_column(
        Enum("pending", "success", "failed", name="job_parse_status"), nullable=False, server_default="pending"
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("0"))
    created_at: Mapped[datetime] = _created_at()


# ⑦ ─────────────────────────────────────────────────────────────
class MatchReport(Base):
    __tablename__ = "match_reports"
    __table_args__ = (
        Index("idx_resume_job", "resume_id", "job_id"),
        Index("idx_job", "job_id"),
        Base.__table_args__,
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "success", "failed", name="match_status"), nullable=False, server_default="pending"
    )
    error_msg: Mapped[str | None] = mapped_column(String(200))
    overall_match: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    passed: Mapped[bool | None] = mapped_column(Boolean, comment="overall_match >= SCREEN_THRESHOLD")
    dimension_scores: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    items: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, comment="逐项匹配明细")
    gap_summary: Mapped[str | None] = mapped_column(Text)

    # 实验参数与统计（匹配消融）
    mode: Mapped[str] = mapped_column(
        Enum("dict_only", "llm_only", "hybrid", name="match_mode"), nullable=False, server_default="hybrid"
    )
    model_name: Mapped[str | None] = mapped_column(String(50))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    llm_item_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="LLM 判定的要求项数")
    hallucination_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="其中引用无法定位的条数"
    )
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, server_default="0")

    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created_at()


# ⑧ ─────────────────────────────────────────────────────────────
class Skill(Base):
    __tablename__ = "skills"
    # 技能同义词词典（扁平）。只回答"这个词是不是某技能的另一种写法"；上下位关系交给 LLM 判定。

    __table_args__ = (Index("idx_category", "category"), Base.__table_args__)

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    category: Mapped[str | None] = mapped_column(String(50), comment="language/backend/frontend/database/devops/ai/data/tool")
    aliases: Mapped[list[str] | None] = mapped_column(JSON, comment="不含规范名本身")
    created_at: Mapped[datetime] = _created_at()


# ⑨ ─────────────────────────────────────────────────────────────
class InterviewSession(Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (
        Index("idx_iv_user", "user_id", "created_at"),
        Index("idx_active", "status", "last_active_at"),
        Base.__table_args__,
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    match_report_id: Mapped[int | None] = mapped_column(ForeignKey("match_reports.id", ondelete="SET NULL"))

    company_name: Mapped[str | None] = mapped_column(String(200))
    extra_context: Mapped[str | None] = mapped_column(LongText, comment="用户粘贴的面经/公司介绍")
    mode: Mapped[str] = mapped_column(
        Enum("normal", "practice", name="interview_mode"), nullable=False, server_default="normal"
    )

    # 状态机游标：面试跨 HTTP 请求，DB 就是检查点
    status: Mapped[str] = mapped_column(
        Enum("planned", "in_progress", "completed", "abandoned", name="interview_status"),
        nullable=False,
        server_default="planned",
    )
    current_round: Mapped[str | None] = mapped_column(Enum("tech", "hr", name="interview_round"))
    current_topic: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    current_depth: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")

    plan: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    model_name: Mapped[str | None] = mapped_column(String(50))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, server_default="0")
    cost_limit: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, server_default="0.3")

    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created_at()

    turns: Mapped[list[InterviewTurn]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="InterviewTurn.turn_no"
    )


# ⑩ ─────────────────────────────────────────────────────────────
class InterviewTurn(Base):
    __tablename__ = "interview_turns"
    __table_args__ = (Index("idx_session", "session_id", "turn_no"), Base.__table_args__)

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False)
    round: Mapped[str] = mapped_column(Enum("tech", "hr", name="turn_round"), nullable=False)
    turn_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="会话内全局序号")
    topic_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    depth: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0", comment="0=主问 1/2=追问")

    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_meta: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    answer: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime)

    evaluation: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment="{scores, evidence[], feedback, better_answer, decision}"
    )
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, server_default="0")
    created_at: Mapped[datetime] = _created_at()

    session: Mapped[InterviewSession] = relationship(back_populates="turns")


# ⑪ ─────────────────────────────────────────────────────────────
class LlmCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("idx_scene", "scene", "created_at"),
        Index("idx_ref", "ref_type", "ref_id"),
        Index("idx_run", "run_id"),
        Base.__table_args__,
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    scene: Mapped[str] = mapped_column(String(50), nullable=False)
    ref_type: Mapped[str | None] = mapped_column(String(30))
    ref_id: Mapped[int | None] = mapped_column(BigInteger)

    provider: Mapped[str | None] = mapped_column(String(30))
    model_name: Mapped[str] = mapped_column(String(50), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(64), comment="system_fingerprint")
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    run_id: Mapped[str | None] = mapped_column(String(36), comment="评测批次；线上为 NULL")

    token_input: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    token_output: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, server_default="0")
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("0"))
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("1"))
    error_msg: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created_at()
