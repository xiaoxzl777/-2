"""匹配图测试：假模型，验证三种 mode 的路径、证据落点、幻觉作废、输出不合格时的降级。"""
import pytest

from app.graphs.match_graph import build_match_graph, initial_state
from tests.conftest import FakeLLM, fulltext_reply as _full
from tests.test_matcher import LINES, STRUCTURE, TEXT, _req

# 在 test_matcher 的简历上：Redis（id=3）规则可判 hit；学历规则可判 hit；其余两条要靠模型
REQS = [_req(1, "skill", "熟悉 Redis", skill_id=3, skill="Redis"), _req(2, "education", "本科及以上学历"),
        _req(3, "experience", "有缓存性能优化经验", req_type="plus"), _req(4, "skill", "熟悉 Kafka")]


def _run(mode, replies):
    llm = FakeLLM(replies)
    state = initial_state(requirements=REQS, structure=STRUCTURE, full_text=TEXT, masked_text=TEXT, mode=mode)
    return llm, build_match_graph(llm).invoke(state)


def test_hybrid_rules_first_then_one_model_call_for_the_rest():
    llm, out = _run("hybrid", {"_FulltextOut": [_full((3, "hit", "列表查询响应从 820ms 降至 140ms"), (4, "miss", None))]})
    items = {i.requirement_id: i for i in out["items"]}
    assert [i.requirement_id for i in out["items"]] == [1, 2, 3, 4]
    assert [(i.status, i.matched_by) for i in out["items"]] == [
        ("hit", "dict"), ("hit", "profile"), ("hit", "fulltext"), ("miss", "fulltext")]

    # 规则判了的不花钱：模型只被调用一次，而且只问了规则判不了的那两条
    assert len(llm.calls["_FulltextOut"]) == 1 and out["llm_item_count"] == 2
    prompt = llm.calls["_FulltextOut"][0][-1][1]
    assert "3. 有缓存性能优化经验" in prompt and "4. 熟悉 Kafka" in prompt and "熟悉 Redis" not in prompt.split("【简历全文】")[0]

    # 模型给的依据被定位回原文
    assert items[3].evidence_quote == "列表查询响应从 820ms 降至 140ms"
    assert TEXT[items[3].char_start:items[3].char_end] == items[3].evidence_quote
    assert out["cost"] == pytest.approx(0.001) and out["hallucination_count"] == 0
    assert out["overall_match"] == round(100 * (1 + 1 + 0.5) / 3.5, 1)
    assert out["dimension_scores"] == {"skill": 50.0, "education": 100.0, "experience": 100.0, "other": None}


def test_claims_without_locatable_evidence_are_voided():
    _, out = _run("hybrid", {"_FulltextOut": [_full((3, "hit", "主导过全公司缓存架构升级"),      # 引用是编的
                                                   (4, "partial", None))]})                 # 说部分满足却不给依据
    assert [(i.status, i.matched_by) for i in out["items"][2:]] == [("miss", "fulltext"), ("miss", "fulltext")]
    assert out["hallucination_count"] == 2 and "作废" in out["items"][2].reason


def test_dict_only_never_calls_the_model():
    llm, out = _run("dict_only", {})
    assert llm.calls == {} and out["llm_item_count"] == 0 and out["cost"] == 0
    assert [(i.status, i.matched_by) for i in out["items"]] == [
        ("hit", "dict"), ("hit", "profile"), ("miss", None), ("miss", None)]


def test_llm_fulltext_skips_the_rules_and_tolerates_missing_answers():
    llm, out = _run("llm_fulltext", {"_FulltextOut": [_full(
        (1, "hit", "热点商品数据预热至 Redis"), (2, "hit", "计算机科学与技术 本科"), (3, "partial", "降至 140ms"))]})
    assert len(llm.calls["_FulltextOut"]) == 1 and out["llm_item_count"] == 4
    assert [(i.status, i.matched_by) for i in out["items"]] == [
        ("hit", "fulltext"), ("hit", "fulltext"), ("partial", "fulltext"), ("miss", "fulltext")]   # 模型漏答的第 4 条按 miss
    assert "没有给出" in out["items"][3].reason


def test_unparseable_output_degrades_to_miss_instead_of_failing_the_match():
    llm, out = _run("hybrid", {"_FulltextOut": ["不是 JSON", "还不是"]})
    assert len(llm.calls["_FulltextOut"]) == 2                                    # 带着错误原因重试过一次
    assert [(i.status, i.matched_by) for i in out["items"]] == [
        ("hit", "dict"), ("hit", "profile"), ("miss", "fulltext"), ("miss", "fulltext")]   # 规则判了的不受影响
    assert out["items"][3].reason == "模型输出无法解析"


def test_nothing_pending_means_no_model_call():
    llm = FakeLLM()
    state = initial_state(requirements=REQS[:2], structure=STRUCTURE, full_text=TEXT, masked_text=TEXT)
    out = build_match_graph(llm).invoke(state)
    assert llm.calls == {} and out["overall_match"] == 100.0 and LINES[3] in out["items"][0].evidence_quote
