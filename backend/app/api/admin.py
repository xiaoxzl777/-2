"""管理端：模型用量、模型设置。全部要管理员登录（deps.require_admin），不是管理员一律 403。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app.errors import BAD_REQUEST, ApiError
from app.llm import provider
from app.llm import status as llm_status
from app.schemas import (
    ApiResponse,
    ProviderIn,
    ProviderKeyIn,
    ProviderOut,
    ProvidersOut,
    ProviderStatusOut,
    ProviderTestOut,
    RetrievalIn,
    RetrievalOut,
    UsageOut,
    ok,
)
from app.services import admin_service, provider_service

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
USAGE_WINDOWS = (0, 7, 30)


@router.get("/usage", response_model=ApiResponse[UsageOut])
def usage(
    days: int = Query(default=7, description="图上画最近几天：7 / 30；0 = 从第一条记录起"),
    day: date | None = Query(default=None, description="四个数和两张表只算这一天"),
    db: Session = Depends(get_db),
):
    """模型用量：只算用户操作产生的调用，按天、按功能、按用户汇总。"""
    if days not in USAGE_WINDOWS:           # 查询串里的数字是字符串，用 Literal[0, 7, 30] 会把 "30" 也拒掉
        raise ApiError(BAD_REQUEST, f"days 只能是 {USAGE_WINDOWS}")
    return ok(admin_service.usage(db, days, day))


@router.get("/providers", response_model=ApiResponse[ProvidersOut])
def list_providers(db: Session = Depends(get_db)):
    """现在用的那一家、其他存着的、添加时可选的预设。API Key 只给开头和后四位。"""
    return ok(provider_service.listing(db))


@router.get("/providers/status", response_model=ApiResponse[ProviderStatusOut])
def provider_status():
    """现问一次现在用的这一家（不走缓存、不花钱）：能不能用、余额。页面先画出来再问它，不拖慢打开速度。"""
    reason, balance = llm_status.check(provider.current())
    return ok(ProviderStatusOut(available=reason is None, reason=reason, balance=balance))


@router.post("/providers/test", response_model=ApiResponse[ProviderTestOut])
def test_new_provider(body: ProviderIn):
    """表单里填的一条，保存之前先试：真调一次模型（几十个 token）。"""
    passed, message, ms = provider_service.test_connection(provider_service.draft(**body.model_dump()))
    return ok(ProviderTestOut(ok=passed, message=message, latency_ms=ms))


@router.post("/providers/{provider_id}/test", response_model=ApiResponse[ProviderTestOut])
def test_saved_provider(provider_id: int, db: Session = Depends(get_db)):
    """已有的一条（0 = .env 那一家）现在还连不连得上。"""
    passed, message, ms = provider_service.test_connection(provider_service.resolve(db, provider_id))
    return ok(ProviderTestOut(ok=passed, message=message, latency_ms=ms))


@router.post("/providers", response_model=ApiResponse[ProviderOut])
def create_provider(body: ProviderIn, db: Session = Depends(get_db)):
    """添加一家。服务端自己再试一次，连不上不存（40001，message 里是原因）。存下来不等于启用。"""
    return ok(provider_service.create(db, provider_service.draft(**body.model_dump())))


@router.put("/providers/{provider_id}/key", response_model=ApiResponse[None])
def change_provider_key(provider_id: int, body: ProviderKeyIn, db: Session = Depends(get_db)):
    """换 Key：先用新 Key 试一次，通过了才换。给 .env 那一家（0）换 Key = 照它的配置在库里存一条并启用。"""
    provider_service.change_key(db, provider_id, body.api_key)
    return ok()


@router.post("/providers/{provider_id}/activate", response_model=ApiResponse[None])
def activate_provider(provider_id: int, db: Session = Depends(get_db)):
    """换成这一家（0 = 换回 .env 那一家）：先试一次，通过了才换。马上生效，正在跑的那一次调用不受影响。"""
    provider_service.activate(db, provider_id)
    return ok()


@router.delete("/providers/{provider_id}", response_model=ApiResponse[None])
def delete_provider(provider_id: int, db: Session = Depends(get_db)):
    """删掉一条配置（正在用的不能删）。以前的用量记录不受影响。"""
    provider_service.remove(db, provider_id)
    return ok()


# ───────────── 检索模型（向量 + 重排）─────────────


@router.get("/retrieval", response_model=ApiResponse[RetrievalOut])
def get_retrieval():
    """检索现在用的哪家、哪两个模型。只在面试时贴了超过 3000 字的面经才用到。"""
    return ok(provider_service.retrieval_view())


@router.get("/retrieval/status", response_model=ApiResponse[ProviderStatusOut])
def retrieval_status():
    """现问一次（只问模型列表，不花钱）：密钥对不对、连不连得上。"""
    r = provider.retrieval()
    reason = llm_status.ping(r.base_url, r.api_key)
    return ok(ProviderStatusOut(available=reason is None, reason=reason, balance=None))


@router.post("/retrieval/test", response_model=ApiResponse[ProviderTestOut])
def test_retrieval(body: RetrievalIn | None = None):
    """真调一次向量和重排。不带请求体 = 试现在用的；带 = 试表单里填的（api_key 留空就用现在的那把）。"""
    r = provider_service.retrieval_draft(**body.model_dump()) if body else provider.retrieval()
    passed, message, ms = provider_service.test_retrieval(r)
    return ok(ProviderTestOut(ok=passed, message=message, latency_ms=ms))


@router.put("/retrieval", response_model=ApiResponse[RetrievalOut])
def save_retrieval(body: RetrievalIn, db: Session = Depends(get_db)):
    """改检索模型：先试，通过了才存（不通过 40001）。向量模型换了的话，已经存着的面经切段一起清掉：
    正在进行的面试照样能面，只是不再带面经。"""
    provider_service.save_retrieval(db, provider_service.retrieval_draft(**body.model_dump()))
    return ok(provider_service.retrieval_view())


@router.delete("/retrieval", response_model=ApiResponse[RetrievalOut])
def reset_retrieval(db: Session = Depends(get_db)):
    """换回 .env 里的配置。"""
    provider_service.reset_retrieval(db)
    return ok(provider_service.retrieval_view())
