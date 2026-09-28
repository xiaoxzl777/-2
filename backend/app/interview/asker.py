"""出题：拼 prompt。调用（流式）在图 B 的 ask_question 节点里。

主问题与追问用同一个 prompt，只有最后的任务不同：追问时带上本话题已经问过的问答和评分员指出的不足，
要求接住候选人上一句里的具体说法往下问。开场白是固定的一句，由代码拼在第一题前面，不花模型的钱。
"""
from __future__ import annotations

from app.interview.materials import describe_source, experience_names
from app.llm import prompts


def intro(materials: dict, topic_count: int) -> str:
    who = f"{materials['company']}的" if materials.get("company") else "这次的"
    return f"你好，我是{who}技术面试官，今天大概聊 {topic_count} 个话题。\n"


def ask_messages(materials: dict, plan: list[dict], topic_idx: int, depth: int, history: list[dict],
                 context: list[str]) -> list[tuple[str, str]]:
    topic = plan[topic_idx]
    material = f"{describe_source(materials, topic)}\n（候选人简历里的经历：{experience_names(materials)}）"
    ctx = ("\n【参考：这家公司的面经 / 介绍】\n" + "\n---\n".join(context)) if context else ""

    asked = [h for h in history if h["topic_idx"] == topic_idx]
    if depth == 0:
        earlier = "、".join(p["label"] for p in plan[:topic_idx])
        past = f"\n【前面已经聊过的话题】{earlier}" if earlier else ""
        task = "请提出这个话题的第一个问题。"
    else:
        lines = []
        for h in asked:
            lines += [f"面试官：{h['question']}", f"候选人：{h['answer'] or '（没有回答）'}"]
        last = asked[-1]["evaluation"] if asked else {}
        if last.get("bad"):
            lines.append(f"（评分员认为上一答的不足：{last['bad']}）")
        past = "\n【这个话题已经问过】\n" + "\n".join(lines)
        task = "请接住候选人上一答里的某个具体说法，追问一次。"

    system = prompts.INTERVIEW_ASK_SYSTEM.format(company=materials.get("company") or "目标公司",
                                                 job_title=materials["job_title"])
    user = prompts.INTERVIEW_ASK_USER.format(label=topic["label"], intent=topic["intent"], material=material,
                                             context=ctx, history=past, task=task)
    return [("system", system), ("user", user)]
