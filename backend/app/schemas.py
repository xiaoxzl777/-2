"""接口的请求 / 响应模型（Pydantic）。所有响应统一包在 ApiResponse 里。"""
from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")

BCRYPT_MAX_BYTES = 72  # bcrypt 只处理前 72 字节，超出直接拒绝，避免"两个不同密码都能登录"


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: T | None = None


def ok(data=None) -> dict:
    return {"code": 0, "message": "success", "data": data}


# ───────────── 认证 ─────────────


class _Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_一-鿿]+$")
    password: str = Field(min_length=6, max_length=64)

    @field_validator("password")
    @classmethod
    def _fits_bcrypt(cls, v: str) -> str:
        if len(v.encode("utf-8")) > BCRYPT_MAX_BYTES:
            raise ValueError("密码过长")
        return v


class RegisterIn(_Credentials):
    email: str | None = Field(default=None, max_length=100, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginIn(_Credentials):
    pass


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    role: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒
    user: UserOut


# ───────────── 简历 ─────────────


class UploadOut(BaseModel):
    id: int
    task_id: str            # "parse:{id}"，用于订阅进度；也可直接轮询 GET /resumes/{id}
    parse_status: str
    deduplicated: bool      # True = 同一文件此前上传过，直接复用那条记录


class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    file_type: str
    file_size: int
    page_count: int | None
    parse_status: str
    parse_error: str | None
    layout_type: str
    layout_confidence: float | None
    used_llm_fallback: bool
    overall_score: float | None
    created_at: datetime
    updated_at: datetime

class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class BlockOut(BaseModel):
    block_index: int
    page_no: int
    column_index: int                 # 0 = 左栏/单栏，1 = 右栏，-1 = 跨栏行
    bbox: list[float] | None          # [x0, y0, x1, y1]；没有版面信息（DOCX）时为 null
    text: str
    font_size: float | None
    is_bold: bool
    char_start: int                   # 相对 full_text，开区间 [start, end)
    char_end: int


class SectionOut(BaseModel):
    type: str
    kind: str | None
    title: str
    block_start: int
    block_end: int
    char_start: int
    char_end: int
    content_start: int
    confidence: float
    matched_by: str
    needs_llm: bool


class BlocksOut(BaseModel):
    """前端渲染与高亮的数据源：按 block_index 顺序渲染 blocks，用 char 区间在 full_text 上定位。"""

    layout_type: str
    layout_confidence: float | None
    layout_detail: list[dict] | None
    used_llm_fallback: bool
    full_text: str
    blocks: list[BlockOut]
    sections: list[SectionOut]

# ───────────── 诊断 ─────────────


class DiagnoseIn(BaseModel):
    mode: Literal["rule_only", "llm_only", "hybrid"] = "hybrid"
    model: str | None = None              # 不填用默认模型；做模型对比实验时指定
    job_title: str | None = Field(default=None, max_length=200)


class TaskOut(BaseModel):
    id: int
    task_id: str
    status: str


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    rule_code: str | None
    risk_type: str | None
    category: str
    severity: str
    title: str
    description: str | None
    suggestion: str | None
    unit_id: str | None
    evidence_quote: str | None
    char_start: int | None
    char_end: int | None
    page_no: int | None
    bbox: list[float] | None
    verify_result: str
    match_score: float | None
    rewrite: dict | None


class DiagnosisStats(BaseModel):
    units_total: int
    units_skipped: int
    rule_finding_count: int
    llm_finding_count: int          # 模型首轮产出的问题数（通过 + 被拦截）
    hallucination_count: int        # 其中引用无法在原文定位、被拦截的条数
    intercept_rate: float | None    # hallucination_count / llm_finding_count
    schema_error_count: int


class DiagnosisOut(BaseModel):
    id: int
    status: str
    error_msg: str | None
    mode: str
    model_name: str | None
    prompt_version: str | None
    job_title: str | None
    overall_score: float | None
    score_detail: dict | None
    stats: DiagnosisStats
    cost: float
    token_input: int
    token_output: int
    started_at: datetime | None
    finished_at: datetime | None
    findings: list[FindingOut]


# ───────────── 岗位 ─────────────


class JobIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    raw_text: str = Field(min_length=30, max_length=10000)    # 粘贴的 JD 原文


class RequirementOut(BaseModel):
    id: int
    req_type: str               # hard / plus / soft
    category: str               # skill / education / experience / other
    content: str
    skill: str | None
    skill_id: int | None        # 词典里有的技能才有；没有的留给匹配阶段的 RAG + LLM 判定
    weight: float
    quote: str                  # JD 原文的逐字引用：raw_text[char_start:char_end]
    char_start: int
    char_end: int


class JobBrief(BaseModel):
    id: int
    title: str
    company: str | None
    is_template: bool
    requirement_count: int
    created_at: datetime


class JobOut(JobBrief):
    raw_text: str
    requirements: list[RequirementOut]


# ───────────── 匹配 ─────────────


class MatchIn(BaseModel):
    resume_id: int
    job_id: int
    mode: Literal["dict_only", "llm_fulltext", "llm_rag", "hybrid"] = "hybrid"
    model: str | None = None


class MatchItemOut(BaseModel):
    requirement_id: int
    content: str
    req_type: str
    category: str
    weight: float
    skill: str | None
    status: str                 # hit / partial / miss
    matched_by: str | None      # dict / profile / rag / fulltext
    reason: str
    evidence_quote: str | None  # 简历原文：full_text[char_start:char_end]
    char_start: int | None
    char_end: int | None
    unit_id: str | None


class MatchReportOut(BaseModel):
    id: int
    resume_id: int
    job_id: int
    status: str
    error_msg: str | None
    mode: str
    model_name: str | None
    prompt_version: str | None
    overall_match: float | None
    passed: bool | None
    threshold: float            # 初筛线：overall_match 达到它即通过
    dimension_scores: dict | None
    items: list[MatchItemOut]
    llm_item_count: int
    hallucination_count: int
    diagnosis_id: int | None
    cost: float
    started_at: datetime | None
    finished_at: datetime | None
