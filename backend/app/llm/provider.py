"""现在用哪一家的对话模型：管理端启用的那一条；一条都没启用，就用 .env 里的 DeepSeek。

进程里只留一份「当前配置」（_current），读它不碰数据库：调模型是高频操作，诊断时十几个请求同时发。
它在两个时候更新：服务启动时从库里读一次（main.lifespan），管理端改了以后再读一次（api/admin.py）。
这依赖服务只有一个进程（见 main.py 开头）。评测脚本不调 load，一直用 .env 的配置，评测结果才好复现。

检索用的向量 / 重排模型（llm/embedding.py）是另一份配置，同样的做法：管理端存了就用它，没存就用 .env 里的硅基流动。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import LlmProvider
from app.security import decrypt_secret

logger = logging.getLogger("app.llm")

# .env 那一家的单价：元 / 百万 token（输入, 输出）。只用来估算花费，实际以平台账单为准
ENV_PRICES: dict[str, tuple[float, float]] = {"deepseek-chat": (4.0, 12.0)}
DEFAULT_PRICE = (4.0, 12.0)

# 管理端「添加供应商」下拉框里的预设：选了自动填接口地址和常用的模型名（都能改）。
# 单价只填了 DeepSeek 的（和上面一致），别家让管理员自己去价格页查了填：写死在这里很快就会过时
PRESETS: dict[str, dict] = {
    "deepseek":    {"name": "DeepSeek",   "base_url": "https://api.deepseek.com", "model": "deepseek-chat", "price_in": 4.0, "price_out": 12.0},
    "siliconflow": {"name": "硅基流动",   "base_url": "https://api.siliconflow.cn/v1", "model": ""},
    "bailian":     {"name": "阿里云百炼", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "zhipu":       {"name": "智谱",       "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-plus"},
    "moonshot":    {"name": "Moonshot",   "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    "custom":      {"name": "其他",       "base_url": "", "model": ""},
}


@dataclass(frozen=True)
class Provider:
    id: int | None            # None = .env 里的那一家
    kind: str                 # PRESETS 的键；限流分桶、审计记录里的 provider 用它
    name: str
    base_url: str
    model: str
    api_key: str              # 明文，只在内存里
    price_in: float           # 元 / 百万 token
    price_out: float

    @property
    def is_deepseek(self) -> bool:
        """DeepSeek 有查余额的接口，也用它自己的 LangChain 封装；别家一律按 OpenAI 兼容接口对待。"""
        host = urlparse(self.base_url).hostname or ""
        return host == "deepseek.com" or host.endswith(".deepseek.com")


@dataclass(frozen=True)
class Retrieval:
    """检索用的两个模型：向量（先召回）和重排（再精排）。只在面试贴了超过 3000 字的面经时用到。"""
    from_env: bool
    base_url: str             # 接口格式同硅基流动：向量走 /embeddings，重排走 /rerank
    api_key: str
    embed_model: str
    rerank_model: str

    @property
    def kind(self) -> str:
        """限流分桶、审计记录里的 provider。"""
        host = urlparse(self.base_url).hostname or ""
        return "siliconflow" if host.endswith("siliconflow.cn") else "custom"

    @property
    def name(self) -> str:
        return "硅基流动" if self.kind == "siliconflow" else "其他"


def env_retrieval() -> Retrieval:
    return Retrieval(True, settings.SILICONFLOW_BASE_URL, settings.SILICONFLOW_API_KEY, settings.EMBEDDING_MODEL, settings.RERANKER_MODEL)


def env_provider() -> Provider:
    price_in, price_out = ENV_PRICES.get(settings.CHAT_MODEL, DEFAULT_PRICE)
    return Provider(None, "deepseek", "DeepSeek", settings.DEEPSEEK_BASE_URL, settings.CHAT_MODEL,
                    settings.DEEPSEEK_API_KEY, price_in, price_out)


_current: Provider | None = None
_retrieval: Retrieval | None = None


def current() -> Provider:
    return _current or env_provider()


def retrieval() -> Retrieval:
    return _retrieval or env_retrieval()


def from_row(row: LlmProvider) -> Provider | None:
    """库里的一行 → 可用的配置。Key 解不开（JWT_SECRET 换过）返回 None。"""
    api_key = decrypt_secret(row.api_key_enc)
    if api_key is None:
        return None
    return Provider(row.id, row.kind, row.name, row.base_url, row.model, api_key, float(row.price_in), float(row.price_out))


def load(db: Session) -> Provider:
    """从库里读启用的那一条，记成当前配置；没有启用的、或者它的 Key 解不开，就退回 .env 那一家。"""
    global _current, _retrieval
    row = db.scalar(select(LlmProvider).where(LlmProvider.purpose == "chat", LlmProvider.is_active).order_by(LlmProvider.id.desc()))
    _current = from_row(row) if row is not None else None
    if row is not None and _current is None:
        logger.error("启用的模型配置（id=%s %s）Key 解不开：JWT_SECRET 换过的话要在管理端重新填 Key。先退回 .env 里的配置", row.id, row.name)
    row = db.scalar(select(LlmProvider).where(LlmProvider.purpose == "retrieval").order_by(LlmProvider.id.desc()))
    key = decrypt_secret(row.api_key_enc) if row is not None else None
    _retrieval = Retrieval(False, row.base_url, key, row.model, row.rerank_model or "") if key else None
    if row is not None and key is None:
        logger.error("检索模型的配置 Key 解不开，先退回 .env 里的配置；要在管理端重新填一遍")
    return current()


def reset() -> None:
    """回到 .env 的配置（测试用）。"""
    global _current, _retrieval
    _current = _retrieval = None


def key_hint(api_key: str) -> str:
    """给页面看的样子：开头 3 位 + 后 4 位。太短的整个盖住，不然等于明文。"""
    return f"{api_key[:3]}••••••••{api_key[-4:]}" if len(api_key) >= 12 else "••••••••"
