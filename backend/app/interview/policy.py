"""推进规则（纯函数）：答完一题之后追问、换话题，还是结束。

模型的 decision 只是建议，追问几次、花多少钱由代码说了算：
  · 花费到了单场上限                         → 结束（按已答的题出报告）
  · 模型说要追问、这题没跳过、追问次数没用完  → 追问
  · 其余                                     → 下一个话题（话题用完了由 pick_topic 转去出报告）
"""
from __future__ import annotations

from typing import Literal

Decision = Literal["followup", "next", "finish"]


def decide(evaluation: dict, depth: int, max_followup: int, cost: float, cost_limit: float) -> Decision:
    if cost >= cost_limit:
        return "finish"
    if not evaluation.get("skipped") and evaluation.get("decision") == "followup" and depth < max_followup:
        return "followup"
    return "next"
