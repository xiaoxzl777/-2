"""图 B：模拟面试（只有一轮专业面：技术面 / 运营面）。走一步、停下来等人回答、再走。

    START ─► plan_interview ─► pick_topic ─┬─► retrieve_context ─► ask_question ─► wait_answer ─► evaluate_answer ─► decide
                                   ▲        └─(话题用完)─► final_report ─► END                ★ interrupt()              │
                                   │                              ▲                                                     │
                                   └──────── next ────────────────┼──────────── finish（成本到顶）───────────────────────┤
                                                ask_question ◄────┴──────────── followup（追问，depth + 1）───────────────┘

· 创建会话时跑到 pick_topic 之前就停（interrupt_before），只把话题定下来；之后每个请求从检查点接着跑。
· wait_answer 里的 interrupt() 让图停住，状态存进检查点（SqliteSaver）；用户答完用 Command(resume=回答) 从原地继续。
· ask_question 流式出题：每段文字经 get_stream_writer() 发出去，service 用 stream_mode="custom" 收到后转成 SSE。
· 节点只收发纯数据，不碰数据库（系统不变量④）；落库由 interview_service 看着每个节点的输出在图外完成。
"""
from __future__ import annotations

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.config import settings
from app.domains import get_domain
from app.graphs.state import InterviewState
from app.interview import asker, policy, rubric
from app.interview.planner import plan_interview
from app.interview.report import build_report
from app.llm import prompts
from app.llm.client import LLMClient, LLMError
from app.retrieval.context_store import ContextStore


class PlanError(Exception):
    """模型两次都没给出能用的面试计划。"""


def _ref(state: InterviewState) -> tuple[str, int]:
    return "interview", state["session_id"]


def build_interview_graph(llm: LLMClient, store: ContextStore | None, checkpointer):
    def _plan(state: InterviewState) -> dict:
        result = plan_interview(state["materials"], state["topic_count"], llm, model=state.get("model"),
                                ref=_ref(state))
        if result.error:
            raise PlanError(result.error)
        return {"plan": result.topics, "cost": result.cost, "topic_idx": -1, "depth": 0}

    def _pick_topic(state: InterviewState) -> dict:
        return {"topic_idx": state["topic_idx"] + 1, "depth": 0}

    def _after_pick(state: InterviewState) -> str:
        return "retrieve_context" if state["topic_idx"] < len(state["plan"]) else "final_report"

    def _retrieve(state: InterviewState) -> dict:
        """方案 C：只检索用户贴的面经。不长就整段给；长的按"话题名 + 考察目标"检索几段；没贴就没有。"""
        materials = state["materials"]
        if materials["context_mode"] == "full":
            return {"context": [materials["context"]]}
        if materials["context_mode"] != "retrieval" or store is None:
            return {"context": []}
        topic = state["plan"][state["topic_idx"]]
        try:
            docs = store.retrieve(state["session_id"], f"{topic['label']} {topic['intent']}",
                                  recall_k=settings.RAG_RECALL_K, top_k=settings.RAG_TOP_K)
        except LLMError:
            docs = []           # 检索挂了照样出题，只是少了参考材料
        return {"context": docs}

    def _ask(state: InterviewState) -> dict:
        write = get_stream_writer()
        idx, depth = state["topic_idx"], state["depth"]
        write({"asking": {"topic_idx": idx, "depth": depth}})          # 先告诉前端这是第几个话题、是不是追问
        opening = asker.intro(state["materials"], len(state["plan"])) if idx == 0 and depth == 0 else ""
        if opening:
            write({"delta": opening})
        messages = asker.ask_messages(state["materials"], state["plan"], idx, depth, state.get("history") or [],
                                      state.get("context") or [])
        text, stats = "", {}
        for piece in llm.stream("interview_ask", messages, prompt_version=prompts.INTERVIEW_VERSION, ref=_ref(state),
                                model=state.get("model"), temperature=0.7, use_cache=False, stats=stats):
            text += piece
            write({"delta": piece})
        if not text.strip():
            raise LLMError("面试官没有给出问题")
        return {"question": opening + text.strip(), "cost": stats.get("cost", 0.0)}

    def _wait(state: InterviewState) -> dict:
        reply = interrupt({"question": state["question"]})        # 图停在这里，直到 Command(resume={text, skip})
        return {"answer": (reply.get("text") or "").strip(), "skipped": bool(reply.get("skip"))}

    def _evaluate(state: InterviewState) -> dict:
        idx, answer = state["topic_idx"], state["answer"]
        if state.get("skipped") or not answer:
            evaluation, cost = rubric.skipped_evaluation(), 0.0
        else:
            evaluation, cost = rubric.evaluate(llm, job_title=state["materials"]["job_title"],
                                               topic=state["plan"][idx], question=state["question"], answer=answer,
                                               model=state.get("model"), ref=_ref(state),
                                               domain=get_domain(state["materials"].get("domain")))
        turn = {"topic_idx": idx, "depth": state["depth"], "question": state["question"], "answer": answer,
                "skipped": evaluation["skipped"], "evaluation": evaluation}
        return {"evaluation": evaluation, "cost": cost, "history": [turn]}

    def _decide(state: InterviewState) -> dict:
        step = policy.decide(state["evaluation"], state["depth"], state["max_followup"], state.get("cost", 0.0),
                             state["cost_limit"])
        return {"next_step": step, "depth": state["depth"] + 1 if step == "followup" else state["depth"]}

    def _route(state: InterviewState) -> str:
        return {"followup": "ask_question", "next": "pick_topic", "finish": "final_report"}[state["next_step"]]

    def _final_report(state: InterviewState) -> dict:
        report, cost = build_report(materials=state["materials"], plan=state["plan"], history=state.get("history") or [],
                                    mode=state["mode"], threshold=state["threshold"], llm=llm,
                                    model=state.get("model"), ref=_ref(state),
                                    early=state.get("next_step") == "finish")
        return {"report": report, "cost": cost}

    graph = StateGraph(InterviewState)
    graph.add_node("plan_interview", _plan)
    graph.add_node("pick_topic", _pick_topic)
    graph.add_node("retrieve_context", _retrieve)
    graph.add_node("ask_question", _ask)
    graph.add_node("wait_answer", _wait)
    graph.add_node("evaluate_answer", _evaluate)
    graph.add_node("decide", _decide)
    graph.add_node("final_report", _final_report)
    graph.add_edge(START, "plan_interview")
    graph.add_edge("plan_interview", "pick_topic")
    graph.add_conditional_edges("pick_topic", _after_pick, ["retrieve_context", "final_report"])
    graph.add_edge("retrieve_context", "ask_question")
    graph.add_edge("ask_question", "wait_answer")
    graph.add_edge("wait_answer", "evaluate_answer")
    graph.add_edge("evaluate_answer", "decide")
    graph.add_conditional_edges("decide", _route, ["ask_question", "pick_topic", "final_report"])
    graph.add_edge("final_report", END)
    return graph.compile(checkpointer=checkpointer)
