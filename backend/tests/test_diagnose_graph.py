"""诊断图测试：假模型 + 手工搭的 structure，验证并行审查、证据校验-重试循环、三种 mode、成本预检、去重。"""
import pytest

from app.graphs.diagnose_graph import build_diagnose_graph, initial_state
from tests.conftest import FakeLLM
from tests.test_rules import Doc, _project

H_VAGUE = "负责系统的优化工作，持续改进各项功能。"
H_GOOD = "热点商品数据预热至 Redis，列表查询响应从 820ms 降至 140ms。"
H_DEEP = "精通 Redis，在项目中使用 Redis 做缓存，QPS 达到 1500。"


def _resume():
    doc = Doc()
    structure = {"projects": [_project(doc, "订单系统", H_VAGUE, H_GOOD, H_DEEP)]}
    return doc.text, structure


def _reply(*items) -> str:
    import json
    return json.dumps({"findings": [
        {"risk_type": t, "severity": s, "evidence_quote": q, "reason": "r", "suggestion": "s"} for t, s, q in items]},
        ensure_ascii=False)


def _run(replies, mode="hybrid", **kw):
    text, structure = _resume()
    llm = FakeLLM(replies)
    state = initial_state(structure=structure, full_text=text, masked_text=text, mode=mode, **kw)
    return text, llm, build_diagnose_graph(llm).invoke(state)


def test_hybrid_runs_both_channels_and_locates_llm_evidence():
    text, llm, out = _run({
        f"_ReviewOut:{H_VAGUE}": [_reply(("vague", "medium", "持续改进各项功能"))],
        f"_ReviewOut:{H_DEEP}": [_reply(("depth_mismatch", "high", "精通 Redis，在项目中使用 Redis 做缓存"))],
    })
    assert out["units_total"] == 3 and out["units_skipped"] == 0
    assert sum(len(calls) for calls in llm.calls.values()) == 3            # 三条经历各审一次，互不干扰

    llm_found = out["llm_findings"]
    assert sorted(f.risk_type for f in llm_found) == ["depth_mismatch", "vague"]
    assert all(f.verify_result == "exact" and text[f.char_start:f.char_end] == f.evidence_quote for f in llm_found)
    assert {f.unit_id for f in llm_found} == {"projects[0].highlights[0]", "projects[0].highlights[2]"}
    assert out["rejected_findings"] == [] and out["schema_errors"] == 0
    assert out["cost"] == pytest.approx(0.003)                              # 并行分支的成本被 reducer 加总

    rule_codes = {f.rule_code for f in out["rule_findings"]}
    assert "STAR_INCOMPLETE" in rule_codes                                  # 规则通道：H_VAGUE 没有结果也没有数字
    assert len(out["findings"]) == len(out["rule_findings"]) + 2
    assert [f.severity for f in out["findings"]] == sorted((f.severity for f in out["findings"]),
                                                           key=["high", "medium", "low"].index)
    assert out["overall_score"] is not None and out["score_detail"]["ats"] == 100.0


def test_fabricated_evidence_is_rejected_then_fixed_on_retry():
    text, llm, out = _run({f"_ReviewOut:{H_VAGUE}": [
        _reply(("vague", "medium", "负责公司核心系统的全面优化"),           # 原文里没有这句话 → 幻觉
               ("unclear_ownership", "low", "持续改进各项功能")),           # 这条是真的
        _reply(("vague", "medium", "负责系统的优化工作")),                   # 重试：老老实实逐字引用
    ]})
    verified, rejected = out["llm_findings"], out["rejected_findings"]

    assert [(f.risk_type, f.attempt_no) for f in verified] == [("unclear_ownership", 1), ("vague", 2)]
    assert [(f.evidence_quote, f.verify_result, f.attempt_no) for f in rejected] == [
        ("负责公司核心系统的全面优化", "failed", 1)]
    assert rejected[0].char_start is None

    # 重试时把定位失败的引用原样告诉了模型
    second_call = llm.calls[f"_ReviewOut:{H_VAGUE}"][1]
    assert second_call[-2][0] == "assistant" and "负责公司核心系统的全面优化" in second_call[-1][1]
    # 被拒的不进最终结果
    assert all(f.verify_result != "failed" for f in out["findings"])


def test_gives_up_after_two_retries():
    fake = _reply(("exaggeration", "high", "主导了整个公司的技术架构升级"))
    _, llm, out = _run({f"_ReviewOut:{H_GOOD}": [fake, fake, fake, fake]})
    assert len(llm.calls[f"_ReviewOut:{H_GOOD}"]) == 3
    assert out["llm_findings"] == [] and [f.attempt_no for f in out["rejected_findings"]] == [1, 2, 3]


def test_evidence_from_another_unit_does_not_count():
    _, _, out = _run({f"_ReviewOut:{H_GOOD}": [_reply(("vague", "low", "持续改进各项功能"))] * 3})   # 这句在 H_VAGUE 里
    assert out["llm_findings"] == [] and len(out["rejected_findings"]) == 3


def test_malformed_output_shares_the_retry_path():
    _, llm, out = _run({f"_ReviewOut:{H_DEEP}": [
        "抱歉，我认为这条写得不错。",
        '{"findings": [{"risk_type": "拼写错误的类型", "severity": "high", "evidence_quote": "x", "reason": "r"}]}',
        _reply(("depth_mismatch", "medium", "精通 Redis")),
    ]})
    assert out["schema_errors"] == 2
    assert [(f.risk_type, f.attempt_no) for f in out["llm_findings"]] == [("depth_mismatch", 3)]
    assert "无法使用" in llm.calls[f"_ReviewOut:{H_DEEP}"][1][-1][1]


def test_formatting_differences_are_tolerated_and_original_text_is_stored():
    text, _, out = _run({f"_ReviewOut:{H_GOOD}": [_reply(("vague", "low", "列表查询响应从 820MS 降至 140MS."))]})
    (f,) = out["llm_findings"]                                              # 大小写不同、末尾多了个句点
    assert f.verify_result == "exact" and f.evidence_quote == "列表查询响应从 820ms 降至 140ms"
    assert text[f.char_start:f.char_end] == f.evidence_quote                # 存的是原文，不是模型写的那一版


def test_rule_only_never_calls_the_model():
    _, llm, out = _run({}, mode="rule_only")
    assert llm.calls == {} and out["llm_findings"] == [] and out["cost"] == 0
    assert out["rule_findings"] and out["units_total"] == 0
    assert all(v is not None for v in out["score_detail"].values())


def test_llm_only_skips_the_rules_and_nulls_their_dimensions():
    _, llm, out = _run({f"_ReviewOut:{H_VAGUE}": [_reply(("vague", "medium", "持续改进各项功能"))]}, mode="llm_only")
    assert out["rule_findings"] == [] and len(out["llm_findings"]) == 1
    assert out["score_detail"] == {"completeness": None, "quantification": None,
                                   "expression": 88.0, "consistency": 100.0, "ats": None}


def test_llm_finding_that_duplicates_a_rule_finding_is_dropped():
    # 规则已经在 H_VAGUE 上报了 WEAK_VERB / STAR（expression / completeness）；模型在同一处报 expression 类 → 去重
    doc = Doc()
    weak = "参与系统的优化工作，持续改进各项功能。"
    structure = {"projects": [_project(doc, "订单系统", weak)]}
    llm = FakeLLM({"_ReviewOut": [_reply(("vague", "medium", "参与系统的优化工作"),           # 与 WEAK_VERB 同处同维度
                                         ("unclear_ownership", "low", "参与系统的优化工作"))]})  # 同处但不同维度 → 保留
    out = build_diagnose_graph(llm).invoke(initial_state(structure=structure, full_text=doc.text, masked_text=doc.text))
    kept = [f for f in out["findings"] if f.source == "llm"]
    assert [f.risk_type for f in kept] == ["unclear_ownership"]
    assert len(out["llm_findings"]) == 2                                    # 原始产出仍然完整，供统计用


def test_cost_limit_truncates_units_before_dispatch():
    _, llm, out = _run({}, cost_limit=0.0065)       # 每单元预估 0.002 × 1.5 = 0.003 → 只够 2 个
    assert out["units_total"] == 3 and out["units_skipped"] == 1
    assert sum(len(c) for c in llm.calls.values()) == 2

    _, llm, out = _run({}, cost_limit=0.0)
    assert llm.calls == {} and out["units_skipped"] == 3 and out["rule_findings"]


def test_pii_masked_text_is_what_the_model_sees():
    doc = Doc()
    structure = {"projects": [_project(doc, "P", "张三独立完成订单模块，联系 13800138000 获取演示。")]}
    from app.parser.pii import mask_pii
    masked = mask_pii(doc.text, name="张三")
    llm = FakeLLM({"_ReviewOut": [_reply(("vague", "low", "某某独立完成订单模块"))]})
    out = build_diagnose_graph(llm).invoke(initial_state(structure=structure, full_text=doc.text, masked_text=masked))

    assert "张三" not in llm.sent_text and "13800138000" not in llm.sent_text
    (f,) = out["llm_findings"]
    assert f.evidence_quote == "张三独立完成订单模块"                         # 在掩码文本上定位，取回的是原文
