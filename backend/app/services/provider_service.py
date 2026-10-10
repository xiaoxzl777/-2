"""管理端的「模型设置」：对话模型可以存几家、选一家用；检索用的向量 + 重排模型只有一份配置（当前用什么见 llm/provider.py）。

规矩只有一条：保存、换 Key、切换之前都先真调一次模型，调不通就不改——填错一个字符，全站的诊断和面试都会停。
试的那一次用和线上一样的 JSON 模式，所以「连得上但不支持 JSON 输出」的模型也会被挡在外面。
"""
from __future__ import annotations

import logging
import time

import httpx
import openai
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.errors import BAD_REQUEST, CONFLICT, NOT_FOUND, ApiError
from app.llm import provider, registry
from app.llm import status as llm_status
from app.llm.client import parse_json, unavailable_reason
from app.llm.provider import PRESETS, Provider, Retrieval
from app.models import LlmProvider
from app.retrieval import context_store
from app.security import decrypt_secret, encrypt_secret

logger = logging.getLogger("app")

ENV_ID = 0                 # 接口里用 0 指 .env 里的那一家（它不在库里，不能删、不能直接改）
_CHAT = LlmProvider.purpose == "chat"              # 对话模型的那些行；检索的配置是另一行（purpose = retrieval）
TEST_TIMEOUT = 20          # 试连的超时（秒）：比正式调用短，页面上有人等着


class _Ping(BaseModel):
    ok: bool


_PING = [("system", "你只输出 JSON，不要输出别的内容。"), ("user", '请原样返回这个 JSON：{"ok": true}')]


def test_connection(p: Provider) -> tuple[bool, str, int | None]:
    """真调一次（几十个 token）。返回 (通过没有, 给管理员看的一句话, 用时毫秒)。"""
    started = time.perf_counter()
    try:
        chat = registry.build_chat_model(p, 0.0, max_retries=0, timeout=TEST_TIMEOUT)
        reply = chat.bind(response_format={"type": "json_object"}).invoke(_PING)
    except Exception as e:  # noqa: BLE001 —— 什么错都要变成一句话告诉管理员
        logger.warning("试连 %s（%s）失败：%s: %s", p.name, p.model, type(e).__name__, str(e)[:200])
        return False, _why(e), None
    ms = int((time.perf_counter() - started) * 1000)
    text = reply.content if isinstance(reply.content, str) else str(reply.content)
    _, error = parse_json(text, _Ping)
    if error:
        return False, "连上了，但回的不是合格的 JSON：这个模型可能不支持 JSON 输出，诊断和匹配用不了", ms
    return True, f"连上了，回的 JSON 合格，用时 {ms / 1000:.1f} 秒", ms


def _why(e: Exception) -> str:
    reason = unavailable_reason(e)          # 余额不足 / 密钥无效 / 服务繁忙 / 连不上
    if reason:
        return reason
    if isinstance(e, openai.APIStatusError):
        if e.status_code == 404:
            return "接口地址或模型名不对（404）"
        return f"这家拒绝了请求（{e.status_code}），多半是模型名不对"
    return f"调用出错（{type(e).__name__}），检查一下接口地址"


# ───────────── 列表 ─────────────


def listing(db: Session) -> dict:
    current = provider.current()
    rows = db.scalars(select(LlmProvider).where(_CHAT).order_by(LlmProvider.id)).all()
    others = [_row_view(r) for r in rows if r.id != current.id]
    if current.id is not None:              # 用着库里的某一条时，.env 那一家排在「其他」的最前面，可以换回去
        others.insert(0, _env_view(active=False))
    mine = next((_row_view(r, active=True) for r in rows if r.id == current.id), None) or _env_view(active=True)
    presets = [{"key": key, **preset} for key, preset in PRESETS.items()]
    return {"current": mine, "others": others, "presets": presets}


def _row_view(row: LlmProvider, active: bool = False) -> dict:
    return {"id": row.id, "kind": row.kind, "name": row.name, "base_url": row.base_url, "model": row.model,
            "key_hint": row.key_hint, "price_in": float(row.price_in), "price_out": float(row.price_out),
            "active": active, "from_env": False, "key_ok": decrypt_secret(row.api_key_enc) is not None}


def _env_view(active: bool) -> dict:
    p = provider.env_provider()
    return {"id": ENV_ID, "kind": p.kind, "name": p.name, "base_url": p.base_url, "model": p.model,
            "key_hint": provider.key_hint(p.api_key) if p.api_key else "", "price_in": p.price_in, "price_out": p.price_out,
            "active": active, "from_env": True, "key_ok": bool(p.api_key)}


# ───────────── 试连 ─────────────


def resolve(db: Session, provider_id: int, api_key: str | None = None) -> Provider:
    """已有的一条（0 = .env 那一家）→ 可以拿去调的配置；给了 api_key 就换成这把新的。"""
    if provider_id == ENV_ID:
        base = provider.env_provider()
    else:
        row = _chat_row(db, provider_id)
        base = provider.from_row(row)
        if base is None and api_key is None:
            raise ApiError(BAD_REQUEST, "这条配置的 Key 读不出来了（JWT_SECRET 换过），请先给它换 Key")
        if base is None:
            base = Provider(row.id, row.kind, row.name, row.base_url, row.model, "", float(row.price_in), float(row.price_out))
    return Provider(base.id, base.kind, base.name, base.base_url, base.model, api_key or base.api_key,
                    base.price_in, base.price_out)


def _chat_row(db: Session, provider_id: int) -> LlmProvider:
    row = db.get(LlmProvider, provider_id) if provider_id != ENV_ID else None
    if row is None or row.purpose != "chat":
        raise ApiError(NOT_FOUND, "这条配置不存在")
    return row


def draft(kind: str, name: str | None, base_url: str, model: str, api_key: str, price_in: float, price_out: float) -> Provider:
    """表单里填的一条（还没存）。"""
    if kind not in PRESETS:
        raise ApiError(BAD_REQUEST, f"未知的供应商：{kind}")
    shown = (name or "").strip() or PRESETS[kind]["name"]
    return Provider(None, kind, shown, base_url.strip().rstrip("/"), model.strip(), api_key.strip(), price_in, price_out)


def _must_pass(p: Provider, what: str) -> None:
    passed, message, _ = test_connection(p)
    if not passed:
        raise ApiError(BAD_REQUEST, f"{message}，{what}")


# ───────────── 增、改、切换、删 ─────────────


def create(db: Session, p: Provider) -> dict:
    _must_pass(p, "没有保存")
    row = LlmProvider(kind=p.kind, name=p.name, base_url=p.base_url, model=p.model, api_key_enc=encrypt_secret(p.api_key),
                      key_hint=provider.key_hint(p.api_key), price_in=p.price_in, price_out=p.price_out)
    db.add(row)
    db.commit()
    return _row_view(row)


def change_key(db: Session, provider_id: int, api_key: str) -> None:
    """换 Key。.env 那一家改不了文件：照它的配置在库里存一条带新 Key 的，并换过去。"""
    p = resolve(db, provider_id, api_key.strip())
    _must_pass(p, "没有改动")
    if provider_id == ENV_ID:
        db.execute(update(LlmProvider).where(_CHAT).values(is_active=False))
        db.add(LlmProvider(kind=p.kind, name=p.name, base_url=p.base_url, model=p.model, api_key_enc=encrypt_secret(p.api_key),
                           key_hint=provider.key_hint(p.api_key), price_in=p.price_in, price_out=p.price_out, is_active=True))
    else:
        row = _chat_row(db, provider_id)
        row.api_key_enc, row.key_hint = encrypt_secret(p.api_key), provider.key_hint(p.api_key)
    db.commit()
    _reload(db)


def activate(db: Session, provider_id: int) -> None:
    _must_pass(resolve(db, provider_id), "没有切换")
    db.execute(update(LlmProvider).where(_CHAT).values(is_active=False))
    if provider_id != ENV_ID:
        _chat_row(db, provider_id).is_active = True
    db.commit()
    _reload(db)


def remove(db: Session, provider_id: int) -> None:
    row = _chat_row(db, provider_id)
    if row.id == provider.current().id:
        raise ApiError(CONFLICT, "正在用的这一条不能删，先换成别的")
    db.delete(row)
    db.commit()


def _reload(db: Session) -> None:
    """改完马上生效：重读当前配置；页面顶上「模型服务不可用」的结论是按旧配置记的，作废。"""
    provider.load(db)
    llm_status.forget()


# ───────────── 检索模型（向量 + 重排）：只有一份配置 ─────────────

_PING_TEXT, _PING_DOCS = "缓存一致性怎么保证", ["先更新数据库再删缓存", "今天天气不错"]


def retrieval_view() -> dict:
    r = provider.retrieval()
    return {"from_env": r.from_env, "name": r.name, "base_url": r.base_url, "key_hint": provider.key_hint(r.api_key) if r.api_key else "",
            "embed_model": r.embed_model, "rerank_model": r.rerank_model}


def retrieval_draft(base_url: str, api_key: str | None, embed_model: str, rerank_model: str) -> Retrieval:
    """表单里填的一份（还没存）。Key 留空 = 沿用现在的那把。"""
    key = (api_key or "").strip() or provider.retrieval().api_key
    return Retrieval(False, base_url.strip().rstrip("/"), key, embed_model.strip(), rerank_model.strip())


def test_retrieval(r: Retrieval) -> tuple[bool, str, int | None]:
    """真调一次：向量一条、重排两条。返回 (通过没有, 给管理员看的一句话, 用时毫秒)。"""
    if not r.api_key:
        return False, "没有配置 API Key", None
    http, headers, base = registry.http_client(), {"Authorization": f"Bearer {r.api_key}"}, r.base_url.rstrip("/")
    started = time.perf_counter()
    try:
        step = "向量"
        reply = http.post(f"{base}/embeddings", json={"model": r.embed_model, "input": [_PING_TEXT]}, headers=headers, timeout=TEST_TIMEOUT)
        reply.raise_for_status()
        dims = len(reply.json()["data"][0]["embedding"])
        step = "重排"
        reply = http.post(f"{base}/rerank", headers=headers, timeout=TEST_TIMEOUT,
                          json={"model": r.rerank_model, "query": _PING_TEXT, "documents": _PING_DOCS, "top_n": 2, "return_documents": False})
        reply.raise_for_status()
        float(reply.json()["results"][0]["relevance_score"])
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        logger.warning("试连检索模型失败（%s）：%s %s", step, code, e.response.text[:200])
        if code in (401, 403):
            return False, f"密钥无效（{code}）", None
        if code == 402:
            return False, "余额不足（402）", None
        if code == 404:
            return False, f"{step}的接口地址不对（404）：这家的接口要和硅基流动一样", None
        if code == 429 or code >= 500:
            return False, f"服务繁忙（{code}）", None
        return False, f"{step}模型被拒绝了（{code}），多半是模型名不对", None
    except httpx.HTTPError as e:
        return False, f"连不上（{type(e).__name__}）", None
    except (KeyError, IndexError, TypeError, ValueError):
        return False, f"{step}接口返回的格式不对：这家的接口和硅基流动不一样，用不了", None
    ms = int((time.perf_counter() - started) * 1000)
    return True, f"连上了：向量 {dims} 维，重排正常，用时 {ms / 1000:.1f} 秒", ms


def save_retrieval(db: Session, r: Retrieval) -> None:
    passed, message, _ = test_retrieval(r)
    if not passed:
        raise ApiError(BAD_REQUEST, f"{message}，没有保存")
    before = provider.retrieval()
    db.execute(delete(LlmProvider).where(LlmProvider.purpose == "retrieval"))
    db.add(LlmProvider(purpose="retrieval", kind=r.kind, name=r.name, base_url=r.base_url, model=r.embed_model, rerank_model=r.rerank_model,
                       api_key_enc=encrypt_secret(r.api_key), key_hint=provider.key_hint(r.api_key), price_in=0, price_out=0, is_active=True))
    db.commit()
    _retrieval_changed(db, before)


def reset_retrieval(db: Session) -> None:
    """换回 .env 里的配置。"""
    before = provider.retrieval()
    db.execute(delete(LlmProvider).where(LlmProvider.purpose == "retrieval"))
    db.commit()
    _retrieval_changed(db, before)


def _retrieval_changed(db: Session, before: Retrieval) -> None:
    provider.load(db)
    now = provider.retrieval()
    if (now.base_url, now.embed_model) != (before.base_url, before.embed_model):
        # 向量模型换了：已经存着的面经切段是按旧模型算的，和新模型算出来的查询向量对不上（维度都可能不同），整个清掉
        logger.warning("向量模型从 %s 换成 %s：清掉向量库里的面经切段", before.embed_model, now.embed_model)
        context_store.drop_all()
