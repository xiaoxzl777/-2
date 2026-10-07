"""面试计划：一次模型调用定下 N 个话题，每个话题必须指向材料里真实存在的一条（经历 / 岗位要求 / 简历问题）。

和 JD 解析同一个思路：模型给出的编号由代码核对，指向不存在的条目、重复的，一律丢掉；
输出不合格（JSON 坏了、一个能用的话题都没有）就带着原因重试一次。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.domains import fill, get_domain
from app.interview.materials import find_source
from app.llm import prompts
from app.llm.client import LLMClient

LABEL_MAX = 20


class _Topic(BaseModel):
    source: Literal["project", "requirement", "finding"]
    ref: str | int
    label: str = Field(min_length=1, max_length=40)
    intent: str = Field(min_length=1, max_length=200)


class _PlanOut(BaseModel):
    topics: list[_Topic]


@dataclass(slots=True)
class PlanResult:
    topics: list[dict] = field(default_factory=list)   # [{idx, source, ref, label, intent}]
    rejected: int = 0                                   # 指向不存在的条目 / 重复而被丢掉的
    cost: float = 0.0
    error: str | None = None


def plan_messages(materials: dict, n: int) -> list[tuple[str, str]]:
    reqs = "\n".join(f"{r['code']} [{r['type']}] {r['content']} —— {r['status']}" for r in materials["requirements"])
    exps = "\n\n".join(f"{e['code']} {e['kind']}：{e['name']}\n{e['text']}" for e in materials["experiences"])
    finds = "\n".join(f"{f['code']} {f['title']} —— 「{f['quote']}」" for f in materials["findings"])
    context = f"\n【面经 / 公司介绍】\n{materials['context']}" if materials.get("context") else ""
    system = prompts.INTERVIEW_PLAN_SYSTEM.format(job_title=materials["job_title"], n=n)
    return [("system", fill(system, get_domain(materials.get("domain")))),
            ("user", prompts.INTERVIEW_PLAN_USER.format(
                job_title=materials["job_title"], requirements=reqs or "（无）", experiences=exps or "（无）",
                findings=finds or "（无）", context=context))]


def plan_interview(materials: dict, n: int, llm: LLMClient, *, model: str | None = None,
                   ref: tuple[str, int] | None = None) -> PlanResult:
    messages = plan_messages(materials, n)
    out = PlanResult()
    for attempt in range(2):
        # 不走缓存：同一次投递再面一次，应该换一批问法
        result = llm.invoke("interview_plan", messages, prompt_version=prompts.INTERVIEW_VERSION, schema=_PlanOut,
                            ref=ref, model=model, temperature=0.7, use_cache=False)
        out.cost += result.cost
        error = result.parse_error
        if result.parsed is not None:
            out.topics, out.rejected = _verify(result.parsed.topics, materials, n)
            if out.topics:
                out.error = None
                return out
            error = "没有一个话题指向材料里真实存在的条目：ref 要照抄材料里每条前面的编号（如 P1、R9、F128）"
        out.error = error
        if attempt == 0:
            messages = [*messages, ("assistant", result.text[:2000]),
                        ("user", prompts.JSON_RETRY.format(error=error))]
    return out


def _verify(items: list[_Topic], materials: dict, n: int) -> tuple[list[dict], int]:
    topics: list[dict] = []
    seen: set[tuple[str, str]] = set()
    rejected = 0
    for t in items:
        ref = str(t.ref).strip().upper()
        if (t.source, ref) in seen or find_source(materials, t.source, ref) is None:
            rejected += 1
            continue
        seen.add((t.source, ref))
        topics.append({"idx": len(topics), "source": t.source, "ref": ref,
                       "label": t.label.strip()[:LABEL_MAX], "intent": t.intent.strip()})
        if len(topics) == n:
            break
    return topics, rejected
