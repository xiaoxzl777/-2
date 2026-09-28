"""模拟面试：创建会话、推进（流式）、提前结束、读取、清理放弃的会话。图 B 只算，落库都在这里。

两份状态（docs/06-workflows 6.3）：
  · MySQL（interview_sessions / interview_turns）是面试记录的权威来源：页面、报告全读它。
    话题计划和材料也存在 sessions.plan 里，所以检查点丢了能从 MySQL 重建。
  · SQLite 检查点只负责让图能从停下的地方接着跑。面试结束就删掉这条线程。

推进只有一个入口 advance：
  answer=None   开始 / 继续（上次中途失败了，从失败的那一步重跑；正在等回答就把那道题再发一次）
  answer=回答    带着回答从 wait_answer 恢复
每个请求把图推进到"又要等人回答"或"面试结束"为止，边跑边产出 SSE 事件：
  topic       {idx, label, source, count}          问到一个新话题（前端这时才把它显示出来）
  asking      {topic_idx, depth}                   开始出题（depth > 0 是追问）
  question    {delta}                              题目逐段
  asked       {turn_id, text, topic_idx, depth}    题目出完了，等回答
  evaluation  {turn_id, ...}                       上一题的点评：只有练习模式才发，跳过的题不发
  finished    {report_ready, verdict, overall}
  error       {code, message}                      什么时候失败都能用 POST /start 从原处继续
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal

from langgraph.types import Command
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import BAD_REQUEST, CONFLICT, LLM_FAILED, NOT_FOUND, ApiError
from app.graphs.checkpoint import thread_config
from app.graphs.interview_graph import PlanError, build_interview_graph
from app.interview.materials import build_materials
from app.interview.report import build_report
from app.llm import prompts
from app.llm.client import LLMClient, LLMError
from app.models import InterviewSession, InterviewTurn, Job, MatchReport, Resume, User
from app.parser.pii import mask_pii
from app.retrieval.context_store import ContextStore
from app.services import diagnose_service
from app.services.parse_service import SessionFactory

logger = logging.getLogger("app.interview")

Event = tuple[str, dict]
FINISHED = ("completed", "abandoned")
_PUBLIC_EVAL = ("skipped", "score", "scores", "evidence", "good", "bad", "better_answer", "decision", "low_evidence")

# 同一场面试同一时刻只能有一个请求在推进图（单进程部署，进程内的锁就够了）
_running: set[int] = set()
_running_guard = threading.Lock()


# ───────────── 创建 ─────────────

def create_interview(db: Session, user: User, *, apply_id: int, company_name: str | None, extra_context: str | None,
                     practice: bool, llm: LLMClient, store: ContextStore | None, checkpointer) -> InterviewSession:
    """同步定下话题（一次模型调用，几秒）。初筛没过的只能练习模式；过了的也可以主动选练习模式。"""
    report = db.get(MatchReport, apply_id)
    resume = db.get(Resume, report.resume_id) if report else None
    if resume is None or resume.user_id != user.id or resume.is_deleted:
        raise ApiError(NOT_FOUND, "投递记录不存在")
    if report.status != "success":
        raise ApiError(CONFLICT, "初筛还没完成，完成后才能面试")
    job = db.get(Job, report.job_id)
    context = (extra_context or "").strip() or None
    session = InterviewSession(
        user_id=user.id, resume_id=resume.id, job_id=job.id, match_report_id=report.id,
        company_name=(company_name or "").strip() or job.company, extra_context=context,
        mode="practice" if practice or not report.passed else "normal", status="planned", current_round="tech",
        model_name=settings.CHAT_MODEL, prompt_version=prompts.INTERVIEW_VERSION,
        cost_limit=Decimal(str(settings.INTERVIEW_COST_LIMIT)))
    db.add(session)
    db.flush()                                          # 先拿到 id：检查点线程、向量库、审计记录都要用

    context_mode = "none" if not context else "full" if len(context) <= settings.INTERVIEW_CONTEXT_FULL_MAX else "retrieval"
    if context_mode == "retrieval":
        try:
            if store is None:
                raise LLMError("向量库不可用")
            store.index(session.id, context)
        except LLMError:
            logger.warning("面经向量化失败，改为截取前 %d 字整段使用 session_id=%s",
                           settings.INTERVIEW_CONTEXT_FULL_MAX, session.id)
            context_mode, context = "full", context[:settings.INTERVIEW_CONTEXT_FULL_MAX]

    structure, full_text = resume.structure or {}, resume.full_text or ""
    findings = [{"id": f.id, "title": f.title, "description": f.description, "char_start": f.char_start,
                 "char_end": f.char_end} for f in diagnose_service.visible_findings(db, report.diagnosis_id)] \
        if report.diagnosis_id else []
    materials = build_materials(
        job_title=job.title, company=session.company_name, requirements=job.requirements or [],
        match_items=report.items or [], structure=structure,
        masked_text=mask_pii(full_text, name=(structure.get("basics") or {}).get("name")),
        findings=findings, context=context, context_mode=context_mode)

    graph = build_interview_graph(llm, store, checkpointer)
    config = thread_config(session.id)
    try:
        graph.invoke(_initial_state(session, materials), config, interrupt_before=["pick_topic"])
    except (PlanError, LLMError) as e:
        logger.warning("生成面试话题失败 session_id=%s：%s", session.id, e)
        _discard(session.id, context_mode, store, checkpointer)
        db.rollback()
        raise ApiError(LLM_FAILED, "生成面试话题失败，请稍后重试") from e

    values = graph.get_state(config).values
    session.plan = {"topics": values["plan"], "materials": materials}
    session.cost = Decimal(str(round(values.get("cost", 0.0), 6)))
    session.last_active_at = datetime.now()
    db.commit()
    return session


def _initial_state(session: InterviewSession, materials: dict) -> dict:
    return {"session_id": session.id, "mode": session.mode, "model": None, "materials": materials,
            "topic_count": settings.INTERVIEW_TOPICS, "max_followup": settings.INTERVIEW_MAX_FOLLOWUP,
            "cost_limit": float(session.cost_limit), "threshold": settings.SCREEN_THRESHOLD,
            "topic_idx": -1, "depth": 0, "cost": 0.0, "history": []}


# ───────────── 推进 ─────────────

def load_owned(db: Session, user: User, session_id: int) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if session is None or session.user_id != user.id:
        raise ApiError(NOT_FOUND, "面试不存在")
    return session


def begin(db: Session, session: InterviewSession) -> None:
    """POST /start 之前：结束了的不能再推进；第一次开始时改成进行中。"""
    if session.status in FINISHED:
        raise ApiError(CONFLICT, "这场面试已经结束了")
    if session.status == "planned":
        db.execute(update(InterviewSession).where(InterviewSession.id == session.id,
                                                  InterviewSession.status == "planned")
                   .values(status="in_progress", started_at=datetime.now(), last_active_at=datetime.now()))
        db.commit()


def submit_answer(db: Session, session: InterviewSession, text: str, skip: bool) -> dict:
    """先把回答落库再恢复图：即使后面评分失败，回答也不会丢。条件更新保证同一题只能答一次（两个标签页同时提交也一样）。"""
    if session.status != "in_progress":
        raise ApiError(CONFLICT, "面试还没开始或已经结束")
    text = "" if skip else text.strip()
    if not skip and not text:
        raise ApiError(BAD_REQUEST, "回答不能为空；不会的话可以跳过这题")
    if len(text) > settings.INTERVIEW_ANSWER_MAX:
        raise ApiError(BAD_REQUEST, f"回答太长了，请控制在 {settings.INTERVIEW_ANSWER_MAX} 字以内")
    last = _last_turn(db, session.id)
    if last is None:
        raise ApiError(CONFLICT, "还没有出题")
    done = db.execute(update(InterviewTurn).where(InterviewTurn.id == last.id, InterviewTurn.answered_at.is_(None))
                      .values(answer=text, answered_at=datetime.now())).rowcount
    if not done:
        raise ApiError(CONFLICT, "这道题已经答过了")
    session.last_active_at = datetime.now()
    db.commit()
    return {"text": text, "skip": skip}


def advance(session_id: int, answer: dict | None, *, llm: LLMClient, store: ContextStore | None, checkpointer,
            session_factory: SessionFactory) -> Iterator[Event]:
    with _running_guard:
        if session_id in _running:
            yield "error", {"code": CONFLICT, "message": "上一步还在进行，请稍等"}
            return
        _running.add(session_id)
    try:
        yield from _advance(session_id, answer, llm, store, checkpointer, session_factory)
    finally:
        with _running_guard:
            _running.discard(session_id)


def _advance(session_id: int, answer: dict | None, llm: LLMClient, store: ContextStore | None, checkpointer,
             session_factory: SessionFactory) -> Iterator[Event]:
    graph = build_interview_graph(llm, store, checkpointer)
    config = thread_config(session_id)
    with session_factory() as db:
        session = db.get(InterviewSession, session_id)
        turns = _turns(db, session_id)
        if not graph.get_state(config).values:
            _rebuild(graph, config, session, turns)
        snapshot = graph.get_state(config)
        mode, plan = session.mode, (session.plan or {}).get("topics") or []

    last = turns[-1] if turns else None
    if snapshot.interrupts:                         # 图正停在 wait_answer
        if answer is None and last is not None and last.answered_at is None:
            yield "asked", _asked(last)             # 页面刷新后重新开始：把正在等的那道题再发一次
            return
        if answer is None and last is not None:     # 回答已经落库、图还没来得及恢复（上次恢复时进程挂了）
            answer = {"text": last.answer or "", "skip": not last.answer}
        command = Command(resume=answer)
    else:
        command = None                              # 从检查点里的下一步接着跑（刚创建，或上次在某一步失败了）

    current = {"topic_idx": snapshot.values.get("topic_idx", -1), "depth": snapshot.values.get("depth", 0)}
    try:
        for kind, chunk in graph.stream(command, config, stream_mode=["custom", "updates"]):
            if kind == "custom":
                yield ("asking", chunk["asking"]) if "asking" in chunk else ("question", {"delta": chunk["delta"]})
                continue
            for node, fields in chunk.items():
                if node not in ("__interrupt__", "retrieve_context", "wait_answer"):
                    yield from _on_update(node, fields or {}, current, session_id, mode, plan, session_factory)
    except Exception:                               # noqa: BLE001 —— 模型失败、输出坏掉都走这里；检查点停在失败的那一步
        logger.exception("面试推进失败 session_id=%s", session_id)
        yield "error", {"code": LLM_FAILED, "message": "面试官这边出了点问题，请重试"}
        return
    if "finished" in current:                       # 图整个跑完（最后一个检查点也写了）才删线程，删早了会被写回来
        _discard(session_id, current["finished"], store, checkpointer)


def _on_update(node: str, fields: dict, current: dict, session_id: int, mode: str, plan: list[dict],
               session_factory: SessionFactory) -> Iterator[Event]:
    """每个节点跑完，按它的输出落库，并决定要不要发事件。"""
    if node in ("pick_topic", "decide"):
        current.update({k: fields[k] for k in ("topic_idx", "depth") if k in fields})
        if node == "pick_topic" and current["topic_idx"] < len(plan):
            topic = plan[current["topic_idx"]]
            with session_factory() as db:
                db.execute(update(InterviewSession).where(InterviewSession.id == session_id)
                           .values(current_topic=topic["idx"], current_depth=0))
                db.commit()
            yield "topic", {"idx": topic["idx"], "label": topic["label"], "source": topic["source"],
                            "count": len(plan)}
        return

    with session_factory() as db:
        session = db.get(InterviewSession, session_id)
        cost = Decimal(str(round(fields.get("cost", 0.0), 6)))
        session.cost += cost
        session.last_active_at = datetime.now()
        if node == "ask_question":
            turn = InterviewTurn(session_id=session_id, round="tech", turn_no=_turn_count(db, session_id) + 1,
                                 topic_idx=current["topic_idx"], depth=current["depth"], question=fields["question"],
                                 question_meta={"label": plan[current["topic_idx"]]["label"],
                                                "source": plan[current["topic_idx"]]["source"]}, cost=cost)
            db.add(turn)
            session.current_depth = current["depth"]
            db.commit()
            yield "asked", _asked(turn)
        elif node == "evaluate_answer":
            turn = _last_turn(db, session_id)
            turn.evaluation = fields["evaluation"]
            turn.cost += cost
            db.commit()
            if mode == "practice" and not fields["evaluation"].get("skipped"):     # 跳过的题不给点评（用户要求）
                yield "evaluation", {"turn_id": turn.id, **public_evaluation(fields["evaluation"])}
        elif node == "final_report":
            report = fields["report"]
            session.report, session.status, session.finished_at = report, "completed", datetime.now()
            current["finished"] = (session.plan or {}).get("materials", {}).get("context_mode")
            db.commit()
            yield "finished", {"report_ready": True, "verdict": report["verdict"], "overall": report["overall"]}
        else:
            db.commit()


def _rebuild(graph, config: dict, session: InterviewSession, turns: list[InterviewTurn]) -> None:
    """检查点丢了：用 MySQL 里的材料、话题和问答把图的状态拼回来，停在该停的那一步。"""
    logger.warning("面试检查点丢失，从数据库重建 session_id=%s", session.id)
    plan = session.plan or {}
    base = {**_initial_state(session, plan.get("materials") or {}), "plan": plan.get("topics") or [],
            "cost": float(session.cost), "history": _history(turns)}
    last = turns[-1] if turns else None
    if last is None:                                            # 还没出过题 → 下一步 pick_topic
        graph.update_state(config, base, as_node="plan_interview")
        return
    at = {"topic_idx": last.topic_idx, "depth": last.depth, "question": last.question}
    if last.evaluation is None:                                 # 题出了、还没评分 → 停回 wait_answer
        graph.update_state(config, {**base, **at, "context": []}, as_node="ask_question")
        for _ in graph.stream(None, config):                    # 跑到 interrupt() 为止
            pass
    else:                                                       # 已经评完分 → 下一步 decide
        graph.update_state(config, {**base, **at, "answer": last.answer or "",
                                    "skipped": bool(last.evaluation.get("skipped")),
                                    "evaluation": last.evaluation}, as_node="evaluate_answer")


# ───────────── 提前结束、读取 ─────────────

def finish_early(db: Session, session: InterviewSession, *, llm: LLMClient, store: ContextStore | None,
                 checkpointer) -> dict:
    """用户点"提前结束"：按已经评完分的题出报告，不经过图（图可能正停在等回答）。"""
    if session.status in FINISHED:
        raise ApiError(CONFLICT, "这场面试已经结束了")
    with _running_guard:
        if session.id in _running:
            raise ApiError(CONFLICT, "上一步还在进行，请稍等")
        _running.add(session.id)
    try:
        plan = session.plan or {}
        report, cost = build_report(materials=plan.get("materials") or {}, plan=plan.get("topics") or [],
                                    history=_history(_turns(db, session.id)), mode=session.mode,
                                    threshold=settings.SCREEN_THRESHOLD, llm=llm, ref=("interview", session.id),
                                    early=True)
        session.report, session.status, session.finished_at = report, "completed", datetime.now()
        session.cost += Decimal(str(round(cost, 6)))
        db.commit()
    finally:
        with _running_guard:
            _running.discard(session.id)
    _discard(session.id, plan.get("materials", {}).get("context_mode"), store, checkpointer)
    return report


def view(db: Session, session: InterviewSession) -> dict:
    """GET /interviews/{id}：只列已经问到的话题（还没问到的不给，免得提前剧透）；
    正常模式在面试结束前不给评分，练习模式每题都给。"""
    plan = (session.plan or {}).get("topics") or []
    turns = _turns(db, session.id)
    reached = max((t.topic_idx for t in turns), default=-1)
    finished = session.status in FINISHED
    show_eval = finished or session.mode == "practice"
    last = turns[-1] if turns else None
    return {
        "id": session.id, "apply_id": session.match_report_id, "job_title": (session.plan or {}).get("materials", {}).get("job_title"),
        "company_name": session.company_name, "mode": session.mode, "status": session.status,
        "topic_count": len(plan),
        "topics": [{"idx": t["idx"], "label": t["label"], "source": t["source"]} for t in plan
                   if finished or t["idx"] <= reached],
        "turns": [_turn_out(t, show_eval) for t in turns],
        "waiting": last is not None and last.answered_at is None and not finished,
        "report_ready": finished and session.report is not None,
    }


def report_view(db: Session, session: InterviewSession) -> dict:
    if session.status not in FINISHED or session.report is None:
        raise ApiError(CONFLICT, "面试还没结束，报告还没生成")
    return {**view(db, session), "report": session.report}


def public_evaluation(evaluation: dict | None) -> dict | None:
    return {k: evaluation.get(k) for k in _PUBLIC_EVAL} if evaluation else None


# ───────────── 启动清理 ─────────────

def cleanup_idle(session_factory: SessionFactory, checkpointer, store_factory=None) -> int:
    """很久没动静的面试 → 按已答的题出报告（不调模型写总结），标成 abandoned。启动时跑一次。"""
    deadline = datetime.now() - timedelta(hours=settings.INTERVIEW_IDLE_HOURS)
    with session_factory() as db:
        rows = db.scalars(select(InterviewSession).where(
            InterviewSession.status.in_(("planned", "in_progress")),
            func.coalesce(InterviewSession.last_active_at, InterviewSession.created_at) < deadline)).all()
        for session in rows:
            plan = session.plan or {}
            session.report, _ = build_report(materials=plan.get("materials") or {}, plan=plan.get("topics") or [],
                                             history=_history(_turns(db, session.id)), mode=session.mode,
                                             threshold=settings.SCREEN_THRESHOLD, llm=None, early=True)
            session.status, session.finished_at = "abandoned", datetime.now()
            db.commit()
            mode = plan.get("materials", {}).get("context_mode")
            _discard(session.id, mode, store_factory() if store_factory and mode == "retrieval" else None, checkpointer)
        return len(rows)


# ───────────── 内部 ─────────────

def _discard(session_id: int, context_mode: str | None, store: ContextStore | None, checkpointer) -> None:
    """面试结束（或创建失败）：删掉检查点线程和面经切段。清理失败不影响结果，只记日志。"""
    try:
        checkpointer.delete_thread(thread_config(session_id)["configurable"]["thread_id"])
        if context_mode == "retrieval" and store is not None:
            store.delete(session_id)
    except Exception:                                   # noqa: BLE001
        logger.exception("清理面试的检查点 / 面经切段失败 session_id=%s", session_id)


def _turns(db: Session, session_id: int) -> list[InterviewTurn]:
    return list(db.scalars(select(InterviewTurn).where(InterviewTurn.session_id == session_id)
                           .order_by(InterviewTurn.turn_no)))


def _last_turn(db: Session, session_id: int) -> InterviewTurn | None:
    return db.scalars(select(InterviewTurn).where(InterviewTurn.session_id == session_id)
                      .order_by(InterviewTurn.turn_no.desc()).limit(1)).first()


def _turn_count(db: Session, session_id: int) -> int:
    return db.scalar(select(func.count()).select_from(InterviewTurn).where(InterviewTurn.session_id == session_id))


def _history(turns: list[InterviewTurn]) -> list[dict]:
    """评完分的题，格式与图 B 状态里的 history 相同。"""
    return [{"topic_idx": t.topic_idx, "depth": t.depth, "question": t.question, "answer": t.answer or "",
             "skipped": bool(t.evaluation.get("skipped")), "evaluation": t.evaluation}
            for t in turns if t.evaluation]


def _asked(turn: InterviewTurn) -> dict:
    return {"turn_id": turn.id, "text": turn.question, "topic_idx": turn.topic_idx, "depth": turn.depth}


def _turn_out(turn: InterviewTurn, show_eval: bool) -> dict:
    evaluation = turn.evaluation or {}
    return {"id": turn.id, "topic_idx": turn.topic_idx, "depth": turn.depth, "question": turn.question,
            "answer": turn.answer if turn.answered_at else None, "skipped": bool(evaluation.get("skipped")),
            "evaluation": public_evaluation(turn.evaluation) if show_eval else None}
