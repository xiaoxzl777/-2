"""匹配图测试：假模型 + 假检索，验证四种 mode 的路径、证据落点、幻觉作废与 miss 复核。"""
import json

import pytest

from app.graphs.match_graph import build_match_graph, initial_state
from app.matching.units import Candidate
from tests.conftest import FakeLLM
from tests.test_matcher import LINES, STRUCTURE, TEXT, _req

# 在 test_matcher 的简历上：Redis（id=3）规则可判 hit；学历规则可判 hit；其余两条要靠模型
REQS = [_req(1, "skill", "熟悉 Redis", skill_id=3, skill="Redis"), _req(2, "education", "本科及以上学历"),
        _req(3, "experience", "有缓存性能优化经验", req_type="plus"), _req(4, "skill", "熟悉 Kafka")]


def _candidate(line_no: int, score=0.5) -> Candidate:
    start = sum(len(l) + 1 for l in LINES[:line_no])
    return Candidate(f"u{line_no}", "projects", "订单系统", start, start + len(LINES[line_no]), LINES[line_no], score)


def _retrieve(query: str) -> list[Candidate]:
    return [_candidate(3), _candidate(1)]


def _judge(status, unit_no=None, reason="r") -> str:
    return json.dumps({"status": status, "unit_no": unit_no, "reason": reason}, ensure_ascii=False)


def _full(*results) -> str:
    return json.dumps({"results": [{"id": i, "status": s, "evidence_quote": q, "reason": "r"} for i, s, q in results]},
                      ensure_ascii=False)


def _run(mode, replies, retrieve=_retrieve):
    llm = FakeLLM(replies)
    state = initial_state(requirements=REQS, structure=STRUCTURE, full_text=TEXT, masked_text=TEXT, mode=mode)
    return llm, build_match_graph(llm, retrieve).invoke(state)


def _calls(llm) -> dict[str, int]:
    return {k.split(":")[0]: sum(len(v) for kk, v in llm.calls.items() if kk.split(":")[0] == k.split(":")[0])
            for k in llm.calls}


def test_hybrid_rules_first_then_rag_then_recheck_of_misses():
    llm, out = _run("hybrid", {
        "_JudgeOut:有缓存性能优化经验": [_judge("hit", 1, "做过缓存预热")],
        "_JudgeOut:熟悉 Kafka": [_judge("miss")],
        "_FulltextOut": [_full((4, "miss", None))],
    })
    items = {i.requirement_id: i for i in out["items"]}
    assert [i.requirement_id for i in out["items"]] == [1, 2, 3, 4]
    assert [(i.status, i.matched_by) for i in out["items"]] == [
        ("hit", "dict"), ("hit", "profile"), ("hit", "rag"), ("miss", "fulltext")]
    assert out["llm_item_count"] == 2 and _calls(llm) == {"_JudgeOut": 2, "_FulltextOut": 1}   # 规则判了的不花钱

    # RAG 的证据 = 模型指认的那个候选单元的区间，取回的是原文
    assert (items[3].unit_id, items[3].evidence_quote) == ("u3", LINES[3])
    assert TEXT[items[3].char_start:items[3].char_end] == LINES[3]
    # 复核只问 RAG 判 miss 的那一条
    recheck_prompt = llm.calls["_FulltextOut"][0][-1][1]
    assert "4. 熟悉 Kafka" in recheck_prompt and "有缓存性能优化经验" not in recheck_prompt
    assert out["cost"] == pytest.approx(0.003) and out["hallucination_count"] == 0
    assert out["overall_match"] == round(100 * (1 + 1 + 0.5) / 3.5, 1)
    assert out["dimension_scores"] == {"skill": 50.0, "education": 100.0, "experience": 100.0, "other": None}


def test_recheck_rescues_what_retrieval_missed():
    _, out = _run("hybrid", {
        "_JudgeOut": [_judge("miss"), _judge("miss")],
        "_FulltextOut": [_full((3, "partial", "列表查询响应从 820ms 降至 140ms"), (4, "miss", None))],
    })
    item = out["items"][2]
    assert (item.status, item.matched_by, item.evidence_quote) == ("partial", "fulltext", "列表查询响应从 820ms 降至 140ms")
    assert TEXT[item.char_start:item.char_end] == item.evidence_quote


def test_claims_without_valid_evidence_are_voided():
    _, out = _run("hybrid", {
        "_JudgeOut:有缓存性能优化经验": [_judge("hit", 7)],                      # 候选只有 2 个，没有 #7
        "_JudgeOut:熟悉 Kafka": [_judge("partial", None)],                       # 说部分满足却不给依据
        "_FulltextOut": [_full((3, "hit", "主导过全公司缓存架构升级"), (4, "miss", None))],   # 引用是编的
    })
    assert [(i.status, i.matched_by) for i in out["items"][2:]] == [("miss", "fulltext"), ("miss", "fulltext")]
    assert out["hallucination_count"] == 3 and "作废" in out["items"][2].reason


def test_dict_only_never_calls_the_model():
    llm, out = _run("dict_only", {}, retrieve=None)
    assert llm.calls == {} and out["llm_item_count"] == 0 and out["cost"] == 0
    assert [(i.status, i.matched_by) for i in out["items"]] == [
        ("hit", "dict"), ("hit", "profile"), ("miss", None), ("miss", None)]


def test_llm_rag_skips_rules_and_recheck():
    llm, out = _run("llm_rag", {"_JudgeOut": [_judge("hit", 1)] * 3 + [_judge("miss")]})
    assert _calls(llm) == {"_JudgeOut": 4} and out["llm_item_count"] == 4
    assert {i.matched_by for i in out["items"]} == {"rag"} and len(out["items"]) == 4
    assert sorted(i.status for i in out["items"]) == ["hit", "hit", "hit", "miss"]


def test_llm_fulltext_judges_everything_in_one_call():
    llm, out = _run("llm_fulltext", {"_FulltextOut": [_full(
        (1, "hit", "热点商品数据预热至 Redis"), (2, "hit", "计算机科学与技术 本科"), (3, "partial", "降至 140ms"))]},
        retrieve=None)
    assert _calls(llm) == {"_FulltextOut": 1}
    assert [(i.status, i.matched_by) for i in out["items"]] == [
        ("hit", "fulltext"), ("hit", "fulltext"), ("partial", "fulltext"), ("miss", "fulltext")]   # 模型漏答的第 4 条按 miss
    assert "没有给出" in out["items"][3].reason


def test_unparseable_output_degrades_to_miss_instead_of_failing_the_match():
    llm, out = _run("llm_rag", {"_JudgeOut:熟悉 Kafka": ["不是 JSON", "还不是"]})
    kafka = out["items"][3]
    assert (kafka.status, kafka.reason) == ("miss", "模型输出无法解析")
    assert len(llm.calls["_JudgeOut:熟悉 Kafka"]) == 2                           # 重试过一次


def test_rag_modes_require_a_retriever_and_empty_retrieval_is_a_miss():
    with pytest.raises(ValueError):
        _run("hybrid", {}, retrieve=None)
    llm, out = _run("llm_rag", {}, retrieve=lambda q: [])
    assert llm.calls == {} and all(i.status == "miss" and "没有检索到" in i.reason for i in out["items"])
