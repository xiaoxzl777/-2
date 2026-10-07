"""随求职方向变化的提示词：按真实调用路径各生成一遍（假模型只记下发出的消息，不回答）。

test_domains.py 用它核对两件事：计算机方向生成的提示词和改造前的快照逐字一样（缓存、评测结果都还对得上）；
换一个方向，提示词跟着变。只有提示词有意改动时才重新拍快照：python -m tests.prompt_cases
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.diagnose.llm_review import review_unit  # noqa: E402
from app.diagnose.types import ReviewUnit  # noqa: E402
from app.interview.asker import ask_messages  # noqa: E402
from app.interview.planner import plan_messages  # noqa: E402
from app.interview.report import build_report  # noqa: E402
from app.interview.rubric import evaluate  # noqa: E402
from app.matching.jd_parser import parse_jd  # noqa: E402
from app.matching.llm_judge import judge_with_fulltext  # noqa: E402
from app.matching.skill_dict import SkillDict  # noqa: E402
from app.rewrite.advice import finding_prompt, gap_prompt  # noqa: E402

SNAPSHOT = Path(__file__).resolve().parent / "data" / "prompts_cs_snapshot.json"

HEAD = "订单系统（后端开发）"
LINE = "负责订单模块开发，接口响应时间降低 50%"
FULL = f"{HEAD}\n{LINE}"
JOB = "后端开发实习生"
STRUCTURE = {"projects": [{"name": "订单系统", "role": "后端开发", "char_start": 0, "char_end": len(FULL),
                           "highlights": [{"char_start": len(HEAD) + 1, "char_end": len(FULL)}]}]}
MATERIALS = {
    "job_title": JOB, "company": "示例科技", "context": None, "context_mode": "none",
    "requirements": [{"code": "R3", "id": 3, "content": "熟悉 Kafka", "type": "必须", "status": "没满足", "reason": "简历里没有"}],
    "experiences": [{"code": "P1", "unit": "projects[0]", "kind": "项目", "name": "订单系统", "text": FULL}],
    "findings": [{"code": "F7", "id": 7, "title": "缺少量化结果", "description": "没写效果", "quote": LINE}],
}
PLAN = [{"idx": 0, "source": "project", "ref": "P1", "label": "订单系统 · 接口", "intent": "确认接口优化是不是本人做的"},
        {"idx": 1, "source": "requirement", "ref": "R3", "label": "消息队列", "intent": "确认是否了解可靠投递"}]
EVALUATION = {"skipped": False, "scores": {"correctness": 4, "depth": 2, "clarity": 4}, "score": 67, "evidence": [],
              "good": "说清了做法", "bad": "没讲效果怎么验证", "better_answer": "", "decision": "followup", "low_evidence": False}
HISTORY = [{"topic_idx": 0, "depth": 0, "question": "接口响应时间是怎么降下来的？", "answer": "加了索引，又把热点数据放进缓存。",
            "evaluation": EVALUATION}]


class _Captured(BaseException):
    """继承 BaseException：被测代码里的 except Exception 拦不住它，记下消息后直接跳出。"""


class _Recorder:
    def __init__(self):
        self.messages: list[list[str]] = []

    def _record(self, messages) -> None:
        self.messages = [list(m) for m in messages]
        raise _Captured

    def invoke(self, scene, messages, **_):
        self._record(messages)

    def stream(self, scene, messages, **_):
        self._record(messages)


def _capture(call) -> list[list[str]]:
    recorder = _Recorder()
    try:
        call(recorder)
    except _Captured:
        return recorder.messages
    raise AssertionError("没有调到模型")


def render_all(domain=None) -> dict[str, list[list[str]]]:
    """domain：不传 = 默认方向（走各函数的默认值）；传一个领域包 = 按那个方向生成。
    面试的几处从面试材料里取方向（创建面试时记在材料里），其余几处是函数参数。"""
    kw = {"domain": domain} if domain else {}
    materials = {**MATERIALS, "domain": domain.key} if domain else MATERIALS
    unit = ReviewUnit("projects[0].highlights[0]", "projects", "订单系统", len(HEAD) + 1, len(FULL), LINE)
    finding = {"unit_id": "projects[0].highlights[0]", "char_start": len(HEAD) + 1, "char_end": len(FULL),
               "title": "缺少量化结果", "description": "没写效果怎么验证"}
    gap = {"content": "熟悉 Kafka", "req_type": "hard", "status": "miss", "reason": "简历里没有", "char_start": None, "char_end": None}
    req = {"id": 3, "content": "熟悉 Kafka", "quote": "熟悉 Kafka 等消息队列"}
    return {
        "diagnose": _capture(lambda llm: review_unit(unit, FULL, FULL, llm, job_title=JOB, rule_summary="无", **kw)),
        "jd_parse": _capture(lambda llm: parse_jd(JOB, "任职要求：熟悉 Redis、MySQL；有高并发项目经验者优先。", llm, SkillDict(()), **kw)),
        "match": _capture(lambda llm: judge_with_fulltext([req], FULL, FULL, llm, **kw)),
        "advice_finding": [list(m) for m in finding_prompt(finding, STRUCTURE, FULL, FULL, JOB, **kw).messages],
        "advice_gap": [list(m) for m in gap_prompt(gap, {"quote": "熟悉 Kafka 等消息队列"}, FULL, FULL, JOB, **kw).messages],
        "interview_plan": [list(m) for m in plan_messages(materials, 5)],
        "interview_ask": [list(m) for m in ask_messages(materials, PLAN, 0, 0, [], [])],
        "interview_followup": [list(m) for m in ask_messages(materials, PLAN, 0, 1, HISTORY, [])],
        "interview_eval": _capture(lambda llm: evaluate(llm, job_title=JOB, topic=PLAN[0], question=HISTORY[0]["question"],
                                                        answer=HISTORY[0]["answer"], **kw)),
        "interview_report": _capture(lambda llm: build_report(materials=materials, plan=PLAN, history=HISTORY, mode="normal",
                                                              threshold=60, llm=llm)),
    }


if __name__ == "__main__":
    SNAPSHOT.parent.mkdir(exist_ok=True)
    SNAPSHOT.write_text(json.dumps(render_all(), ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"已写入 {SNAPSHOT}")
