"""管理端：管理员账号、模型用量统计。

用量全部来自 llm_calls（每调一次模型记一行，llm/audit.py）。这张表记的是「哪次诊断 / 哪场面试」（ref_type + ref_id），
没有直接记用户，所以统计分两步：先按「哪一天、哪个场景、挂在哪个对象上」汇总，再去查这些对象是谁的。
只算用户操作产生的调用：评测批次（run_id 不为空）和脚本跑的（没有挂对象）另算一个总数。
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Diagnosis, Finding, InterviewSession, Job, LlmCall, MatchReport, Resume, User
from app.security import hash_password

logger = logging.getLogger("app")

# ───────────── 管理员账号 ─────────────


def is_reserved(username: str) -> bool:
    """管理员的用户名不让别人注册（不分大小写）。"""
    return username.lower() == settings.ADMIN_USERNAME.lower()


def ensure_admin(db: Session) -> None:
    """启动时调：没有管理员账号就按配置建一个。已经有了就不动它——密码可能在页面上改过。"""
    user = db.scalar(select(User).where(User.username == settings.ADMIN_USERNAME))
    if user is None:
        db.add(User(username=settings.ADMIN_USERNAME, password_hash=hash_password(settings.ADMIN_PASSWORD), role="admin"))
        db.commit()
        logger.info("已创建管理员账号 %s", settings.ADMIN_USERNAME)
    elif user.role != "admin":
        # 以前有人用这个名字注册过普通账号：不替它升成管理员（那等于把管理端交给了注册的人）
        logger.error("用户名 %s 已被普通账号占用，没有创建管理员。请在 .env 里把 ADMIN_USERNAME 改成别的名字", settings.ADMIN_USERNAME)


# ───────────── 模型用量 ─────────────

# 页面上「按功能」的几行，按流程的先后排；other 只在有调用时才出现
FEATURES = [("parse", "简历解析"), ("jd", "岗位解析"), ("diagnose", "诊断"), ("match", "匹配"),
            ("advice", "具体建议"), ("interview", "模拟面试"), ("other", "其他")]
_SCENE_FEATURE = {"structure": "parse", "section": "parse", "jd_parse": "jd", "diagnose": "diagnose", "match": "match",
                  "rewrite": "advice", "gap": "advice", "embed": "interview", "rerank": "interview"}

USER_CALLS = and_(LlmCall.run_id.is_(None), LlmCall.ref_id.is_not(None))     # 用户操作产生的调用
_FIELDS = ("calls", "cached", "failed", "token_input", "token_output", "cost")
_IN_CHUNK = 500
FAILURES_SHOWN = 20                 # 「最近失败」最多列几条
_HTTP_CODE = re.compile(r"Error code: (\d{3})|'(\d{3}) [A-Z]")     # openai 的报错 / httpx 的报错里的状态码
_KEY_LIKE = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")


def failure_reason(error_msg: str | None) -> str:
    """llm_calls.error_msg 是给开发者看的（异常类型 + 服务商的原话），这里归成管理员看得懂的一句。"""
    text = error_msg or ""
    if "提前结束了流式读取" in text:
        return "页面中途关了或刷新了，没生成完"
    if "限流占位失败" in text:
        return "排队等名额超时，或者 Redis 连不上"
    if m := _HTTP_CODE.search(text):
        code = int(m.group(1) or m.group(2))
        if code == 402:
            return "余额不足（402）"
        if code in (401, 403):
            return f"密钥无效（{code}）"
        if code == 429:
            return "请求太快，被服务商限流（429）"
        if code == 404:
            return "接口地址或模型名不对（404）"
        if code >= 500:
            return f"模型服务自己出错了（{code}）"
        return f"请求被拒绝（{code}），多半是模型名不对"
    if re.search(r"timeout|timed out", text, re.I):
        return "超时"
    if re.search(r"connect", text, re.I):
        return "连不上模型服务"
    return "其他错误"


def feature_of(scene: str) -> str:
    return _SCENE_FEATURE.get(scene) or ("interview" if scene.startswith("interview") else "other")


def _zero() -> dict:
    return {"calls": 0, "cached": 0, "failed": 0, "token_input": 0, "token_output": 0, "cost": 0.0}


def _add(total: dict, row: dict) -> None:
    for k in _FIELDS:
        total[k] += row[k]


def _rounded(total: dict) -> dict:
    return {**total, "cost": round(total["cost"], 6)}


def usage(db: Session, days: int, day: date | None = None, today: date | None = None) -> dict:
    """days：图上画最近几天（0 = 从第一条记录起）；day：四个数和两张表只算这一天（要在图的范围里）。"""
    today = today or date.today()
    start = today - timedelta(days=days - 1) if days else _first_day(db, today)
    if day is not None and not start <= day <= today:
        day = None
    rows = _grouped(db, start, today)
    owners = _owners(db, {(r["ref_type"], r["ref_id"]) for r in rows})

    by_day = {start + timedelta(days=i): _zero() for i in range((today - start).days + 1)}
    features: dict[str, dict] = defaultdict(_zero)
    users: dict[int | None, dict] = defaultdict(lambda: {**_zero(), "last_used": None})
    total, window_cost = _zero(), 0.0
    for r in rows:
        _add(by_day[r["date"]], r)
        window_cost += r["cost"]
        if day is not None and r["date"] != day:
            continue
        _add(total, r)
        _add(features[feature_of(r["scene"])], r)
        mine = users[owners.get((r["ref_type"], r["ref_id"]))]
        _add(mine, r)
        mine["last_used"] = max(filter(None, (mine["last_used"], r["date"])))

    since, until = (day, day) if day is not None else (start, today)
    names = _usernames(db, {uid for uid in users if uid is not None})
    counts = _activity(db, since, until)
    gone = {**_zero(), "last_used": None}                     # 对象或账号已经删掉的，合成一行
    listed = []
    for uid, u in users.items():
        if uid not in names:
            _add(gone, u)
            continue
        listed.append({"user_id": uid, "username": names[uid], **_rounded(u), **counts.get(uid, _NO_ACTIVITY)})
    listed.sort(key=lambda u: -u["cost"])
    if gone["calls"]:
        listed.append({"user_id": None, "username": None, **_rounded(gone), **_NO_ACTIVITY, "last_used": None})

    other_calls, other_cost = db.execute(select(func.count(), func.coalesce(func.sum(LlmCall.cost), 0))
                                         .where(or_(LlmCall.run_id.is_not(None), LlmCall.ref_id.is_(None)))).one()
    return {
        "days": days, "day": day, "today": today, "total": _rounded(total), "window_cost": round(window_cost, 6),
        "today_cost": round(by_day[today]["cost"], 6),
        "by_day": [{"date": d, **_rounded(v)} for d, v in by_day.items()],
        "features": [{"key": key, "name": name, **_rounded(features[key])} for key, name in FEATURES
                     if key != "other" or features[key]["calls"]],
        "users": listed,
        "failures": _failures(db, since, until, owners, names),
        "registered": db.scalar(select(func.count()).select_from(User).where(User.role == "seeker")) or 0,
        "other_calls": other_calls, "other_cost": round(float(other_cost), 6),
    }


_NO_ACTIVITY = {"resumes": 0, "applies": 0, "interviews": 0}


def _span(since: date, until: date) -> tuple[datetime, datetime]:
    return datetime.combine(since, datetime.min.time()), datetime.combine(until + timedelta(days=1), datetime.min.time())


def _first_day(db: Session, today: date) -> date:
    first = db.scalar(select(func.min(LlmCall.created_at)).where(USER_CALLS))
    return min(first.date(), today) if first else today


def _grouped(db: Session, since: date, until: date) -> list[dict]:
    """这段时间里用户操作产生的调用，按（哪一天、哪个场景、挂在哪个对象上）汇总。"""
    start, end = _span(since, until)
    day_col = func.date(LlmCall.created_at)
    stmt = (select(day_col, LlmCall.scene, LlmCall.ref_type, LlmCall.ref_id, func.count(),
                   func.sum(case((LlmCall.cache_hit.is_(True), 1), else_=0)),
                   func.sum(case((LlmCall.success.is_(True), 0), else_=1)),
                   func.sum(LlmCall.token_input), func.sum(LlmCall.token_output), func.sum(LlmCall.cost))
            .where(USER_CALLS, LlmCall.created_at >= start, LlmCall.created_at < end)
            .group_by(day_col, LlmCall.scene, LlmCall.ref_type, LlmCall.ref_id))
    return [{"date": date.fromisoformat(str(d)[:10]),         # MySQL 给的是日期，SQLite 给的是字符串
             "scene": scene, "ref_type": ref_type, "ref_id": ref_id, "calls": int(calls), "cached": int(cached),
             "failed": int(failed), "token_input": int(tin), "token_output": int(tout), "cost": float(cost)}
            for d, scene, ref_type, ref_id, calls, cached, failed, tin, tout, cost in db.execute(stmt)]


def _owners(db: Session, refs: set[tuple[str, int]]) -> dict[tuple[str, int], int | None]:
    """(ref_type, ref_id) → 用户 id。每种对象一条查询；对象已经不在了的不出现在结果里。"""
    lookups = {
        "resume": (Resume.id, select(Resume.id, Resume.user_id)),
        "diagnosis": (Diagnosis.id, select(Diagnosis.id, Resume.user_id).join(Resume, Resume.id == Diagnosis.resume_id)),
        "match_report": (MatchReport.id, select(MatchReport.id, Resume.user_id).join(Resume, Resume.id == MatchReport.resume_id)),
        "finding": (Finding.id, select(Finding.id, Resume.user_id).join(Diagnosis, Diagnosis.id == Finding.diagnosis_id)
                    .join(Resume, Resume.id == Diagnosis.resume_id)),
        "job": (Job.id, select(Job.id, Job.user_id)),
        "interview": (InterviewSession.id, select(InterviewSession.id, InterviewSession.user_id)),
    }
    wanted: dict[str, list[int]] = defaultdict(list)
    for ref_type, ref_id in refs:
        wanted[ref_type].append(ref_id)
    owners: dict[tuple[str, int], int | None] = {}
    for ref_type, ids in wanted.items():
        if ref_type not in lookups:
            continue
        id_col, stmt = lookups[ref_type]
        for i in range(0, len(ids), _IN_CHUNK):
            for ref_id, user_id in db.execute(stmt.where(id_col.in_(ids[i:i + _IN_CHUNK]))):
                owners[(ref_type, ref_id)] = user_id
    return owners


def _failures(db: Session, since: date, until: date, owners: dict, names: dict[int, str]) -> list[dict]:
    """这段时间里最近失败的几次调用：什么时候、哪个功能、谁的、为什么。原始报错里 Key 样子的串盖掉再给。"""
    start, end = _span(since, until)
    rows = db.execute(select(LlmCall.created_at, LlmCall.scene, LlmCall.ref_type, LlmCall.ref_id, LlmCall.error_msg)
                      .where(USER_CALLS, LlmCall.success.is_(False), LlmCall.created_at >= start, LlmCall.created_at < end)
                      .order_by(LlmCall.created_at.desc(), LlmCall.id.desc()).limit(FAILURES_SHOWN))
    label = dict(FEATURES)
    return [{"at": at, "feature": label[feature_of(scene)], "username": names.get(owners.get((ref_type, ref_id))),
             "reason": failure_reason(error_msg), "detail": _KEY_LIKE.sub("sk-…", error_msg or "（没有记下报错内容）")}
            for at, scene, ref_type, ref_id, error_msg in rows]


def _usernames(db: Session, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    return dict(db.execute(select(User.id, User.username).where(User.id.in_(user_ids))).all())


def _activity(db: Session, since: date, until: date) -> dict[int, dict]:
    """这段时间里每个用户传了几份简历、投了几次、面了几场（删掉的也算：那也是用过）。"""
    start, end = _span(since, until)
    out: dict[int, dict] = defaultdict(lambda: dict(_NO_ACTIVITY))
    queries = {
        "resumes": select(Resume.user_id, func.count()).where(Resume.created_at >= start, Resume.created_at < end).group_by(Resume.user_id),
        "applies": (select(Resume.user_id, func.count()).join(MatchReport, MatchReport.resume_id == Resume.id)
                    .where(MatchReport.created_at >= start, MatchReport.created_at < end).group_by(Resume.user_id)),
        "interviews": (select(InterviewSession.user_id, func.count())
                       .where(InterviewSession.created_at >= start, InterviewSession.created_at < end)
                       .group_by(InterviewSession.user_id)),
    }
    for key, stmt in queries.items():
        for user_id, n in db.execute(stmt):
            out[user_id][key] = n
    return out
