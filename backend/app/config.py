"""全局配置：从 .env 读取（pydantic-settings）。

约定：
- 所有阈值 / 常数集中在这里，代码里不出现魔法数字。
- 仓库只提交 .env.example；本机与两台电脑各自维护 .env。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录；.env 放在项目根 D:\final\.env，也允许放在 backend\.env
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_ROOT_DIR = _BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_ROOT_DIR / ".env", _BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: str = "dev"

    # ---- 存储 ----
    DATABASE_URL: str = "mysql+pymysql://root:your_password@localhost:3306/resume_ai?charset=utf8mb4"
    REDIS_URL: str = "redis://localhost:6379/0"
    DATA_DIR: Path = _ROOT_DIR / "data"

    # ---- 认证 ----
    JWT_SECRET: str = "change-me"
    JWT_EXPIRE_HOURS: int = 24

    # ---- 模型 ----
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    CHAT_MODEL: str = "deepseek-chat"
    SILICONFLOW_API_KEY: str = ""
    SILICONFLOW_BASE_URL: str = "https://api.siliconflow.cn/v1"
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    LLM_TIMEOUT_SECONDS: float = 60.0
    LLM_USE_SYSTEM_PROXY: bool = False         # 本机配了 HTTP(S)_PROXY 时，国内模型服务直连更快（实测 1s vs 5s）
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"

    # ---- 上传校验（FR-B1）----
    MAX_UPLOAD_MB: int = 20
    MAX_DOCX_UNZIP_MB: int = 100
    MAX_PDF_PAGES: int = 10
    MAX_DOCX_CHARS: int = 30_000
    SCANNED_PDF_MIN_CHARS: int = 100

    # ---- 版面分栏常数（5.1）----
    LAYOUT_HEADER_FOOTER_RATIO: float = 0.06   # 页顶/页底比例内视为页眉页脚候选
    LAYOUT_MIN_GAP_RATIO: float = 0.03         # 空白带最小宽度 / 页宽
    LAYOUT_SINGLE_MAX_C: float = 0.30          # c 低于此值判 single
    LAYOUT_DOUBLE_MIN_C: float = 0.80          # c 高于此值判 double
    LAYOUT_TABLE_CHAR_RATIO: float = 0.70      # 表格字符占比高于此值判 table
    LAYOUT_FALLBACK_CONF: float = 0.70         # 置信度低于此值触发 LLM 兜底

    # ---- 诊断 / 匹配 / 面试 ----
    DIAGNOSE_COST_LIMIT: float = 0.05          # 元
    UNIT_COST_EST: float = 0.002               # 每条经历预估成本（元），成本预检用
    EVIDENCE_FUZZY_MIN: int = 90               # RapidFuzz 模糊匹配通过分
    SCREEN_THRESHOLD: float = 60.0             # 初筛通过分
    RAG_RECALL_K: int = 20                     # 第一阶段 embedding 召回条数
    RAG_TOP_K: int = 3                         # 第二阶段 rerank 后注入 prompt 的条数
    MATCH_RECALL_K: int = 10                   # 匹配：一份简历只有十几个单元，召回 10 个再精排
    INTERVIEW_COST_LIMIT: float = 0.3          # 元
    INTERVIEW_TECH_MAX_Q: int = 8
    INTERVIEW_HR_MAX_Q: int = 6
    INTERVIEW_MAX_FOLLOWUP: int = 2
    INTERVIEW_IDLE_HOURS: int = 24

    # ---- 缓存 / 限流 ----
    LLM_CACHE_TTL_SECONDS: int = 7 * 24 * 3600
    DEEPSEEK_RPM: int = 60
    SILICONFLOW_RPM: int = 300

    @field_validator("DATA_DIR")
    @classmethod
    def _absolute_data_dir(cls, v: Path) -> Path:
        """相对路径一律相对 backend/ 解析，不受"从哪个目录启动服务"影响。"""
        return v if v.is_absolute() else (_BACKEND_DIR / v).resolve()

    @property
    def uploads_dir(self) -> Path:
        return self.DATA_DIR / "uploads"

    @property
    def chroma_dir(self) -> Path:
        return self.DATA_DIR / "chroma"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
