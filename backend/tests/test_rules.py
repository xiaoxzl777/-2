from datetime import date

import pytest

from app.diagnose.rules import RULES, RuleContext, run_rules
from app.diagnose.scorer import score
from app.diagnose.types import Finding, iter_units


class Doc:
    """按行拼出 full_text，并记下每行的区间，方便手工搭 structure。"""

    def __init__(self):
        self.lines: list[str] = []

    def add(self, text: str) -> dict:
        start = sum(len(l) + 1 for l in self.lines)
        self.lines.append(text)
        return {"char_start": start, "char_end": start + len(text), "text": text}

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _project(doc: Doc, name: str, *highlights: str) -> dict:
    title = doc.add(f"{name} 后端开发")
    hs = [doc.add(h) for h in highlights]
    return {"name": name, "char_start": title["char_start"], "char_end": (hs[-1] if hs else title)["char_end"],
            "highlights": hs}


def _run(doc: Doc, structure: dict, **kw) -> list[Finding]:
    return run_rules(RuleContext(structure=structure, full_text=doc.text, today=date(2026, 9, 1), **kw))


def _codes(findings) -> list[str]:
    return [f.rule_code for f in findings]


def test_all_seven_rules_are_registered():
    assert set(RULES) == {"NO_QUANTIFICATION", "STAR_INCOMPLETE", "WEAK_VERB", "SKILL_PROJECT_MISMATCH",
                          "TIMELINE_ANOMALY", "ATS_UNFRIENDLY", "LENGTH_ANOMALY"}


def test_a_strong_highlight_raises_nothing():
    doc = Doc()
    p = _project(doc, "订单系统", "热点商品数据预热至 Redis，列表查询响应从 820ms 降至 140ms，DB 访问频次压降 60%。")
    assert _run(doc, {"projects": [p]}) == []


def test_result_without_numbers_vs_no_result_at_all():
    doc = Doc()
    p = _project(doc, "订单系统",
                 "负责优化系统性能，提升了响应速度。",                       # 有结果词、没数字 → 缺量化
                 "独立完成用户、商品、订单模块接口设计与开发。",             # 没结果也没数字 → STAR 不完整
                 "基于 Vue3 与 JDK8 开发后台，英语 CET-6。")                # 名称 / 版本号里的数字不算量化
    findings = _run(doc, {"projects": [p]})
    assert _codes(findings) == ["NO_QUANTIFICATION", "STAR_INCOMPLETE", "STAR_INCOMPLETE"]

    quant = findings[0]
    assert (quant.category, quant.severity, quant.source, quant.verify_result) == ("quantification", "high", "rule", "exact")
    assert quant.evidence_quote == "提升了响应速度" and quant.unit_id == "projects[0].highlights[0]"
    # 每条规则证据都是 full_text 的精确切片
    assert all(doc.text[f.char_start:f.char_end] == f.evidence_quote for f in findings)


def test_subheading_plus_body_units():
    doc = Doc()
    p = _project(doc, "电商平台", "性能优化：\n热点数据预热至 Redis，查询响应从 820ms 降至 140ms。",
                 "核心业务开发：\n独立完成四大模块的接口设计。")
    findings = _run(doc, {"projects": [p]})
    assert _codes(findings) == ["STAR_INCOMPLETE"]                  # 小标题里的"性能"不算在陈述结果
    assert findings[0].evidence_quote == "独立完成四大模块的接口设计"     # 证据取正文，不取小标题


def test_list_numbering_is_not_quantification():
    doc = Doc()
    p = _project(doc, "订单系统",
                 "1. 负责系统的优化工作，持续改进各项功能。",                 # 编号不是量化数字
                 "（2）优化了查询逻辑，提升了响应速度。",
                 "3. 10.5% 的慢查询被消除，接口 P99 降至 120ms。",          # 行首的小数不是编号
                 "4、完成 12 个接口的开发并上线。")
    findings = _run(doc, {"projects": [p]})
    assert _codes(findings) == ["NO_QUANTIFICATION", "STAR_INCOMPLETE"]
    assert findings[1].evidence_quote == "负责系统的优化工作，持续改进各项功能"   # 证据不带编号


@pytest.mark.parametrize(
    ("line", "quote"),
    [
        ("参与用户模块开发，协助完成接口联调", "参与用户模块开发"),
        ("- 协助导师完成数据清洗", "协助导师完成数据清洗"),
        ("2. 了解微服务架构的基本原理", "了解微服务架构的基本原理"),
        ("核心开发：\n配合后端完成 3 个页面的联调", "配合后端完成 3 个页面的联调"),
    ],
)
def test_weak_verb(line, quote):
    doc = Doc()
    weak = [f for f in _run(doc, {"projects": [_project(doc, "P", line)]}) if f.rule_code == "WEAK_VERB"]
    assert len(weak) == 1 and weak[0].evidence_quote == quote and weak[0].severity == "low"


def test_weak_verb_only_at_the_start_of_a_line():
    doc = Doc()
    p = _project(doc, "P", "深入了解业务后设计了缓存方案，接口 P99 从 800ms 降至 120ms")
    assert "WEAK_VERB" not in _codes(_run(doc, {"projects": [p]}))


def test_skill_listed_but_never_used():
    doc = Doc()
    skills_line = doc.add("熟悉 SpringBoot、Kubernetes、Feign、Seata")

    def skill(name, skill_id):
        at = skills_line["char_start"] + skills_line["text"].index(name)
        return {"name": name, "skill_id": skill_id, "char_start": at, "char_end": at + len(name)}

    project = _project(doc, "订单系统", "基于 spring-boot 与 feign 完成 12 个接口，QPS 达到 1500")
    structure = {
        "skills": [skill("SpringBoot", 3), skill("Kubernetes", 11), skill("Feign", None), skill("Seata", None)],
        "projects": [project],
        # 词典认识 spring-boot（写法不同也算用过）；Feign 不在词典里，靠字面查找
        "skill_mentions": [{"skill_id": 3, "section_type": "projects"}, {"skill_id": 11, "section_type": "skills"}],
    }
    found = [f for f in _run(doc, structure) if f.rule_code == "SKILL_PROJECT_MISMATCH"]
    assert [f.evidence_quote for f in found] == ["Kubernetes", "Seata"]
    assert all(f.category == "consistency" and f.unit_id is None for f in found)

    # 没有任何经历时，这条规则没有意义
    assert "SKILL_PROJECT_MISMATCH" not in _codes(_run(doc, {"skills": structure["skills"], "projects": []}))


def test_skill_findings_are_capped():
    doc = Doc()
    line = doc.add(" ".join(f"Tool{i}" for i in range(10)))
    skills = [{"name": f"Tool{i}", "skill_id": None, "char_start": line["char_start"] + line["text"].index(f"Tool{i}"),
               "char_end": line["char_start"] + line["text"].index(f"Tool{i}") + 5} for i in range(10)]
    structure = {"skills": skills, "projects": [_project(doc, "P", "完成 5 个接口，响应降至 100ms")]}
    assert _codes(_run(doc, structure)).count("SKILL_PROJECT_MISMATCH") == 5


def test_timeline_gap_and_overlap():
    doc = Doc()

    def job(name, start, end, kind="internship", present=False):
        span = doc.add(f"{name} 后端实习生 {start}")
        body = doc.add("完成 5 个接口，响应从 300ms 降至 90ms")
        return {"name": name, "kind": kind, "start": start, "end": end, "is_present": present,
                "char_start": span["char_start"], "char_end": body["char_end"], "highlights": [body]}

    work = [job("A 公司", "2024-01", "2024-06"),
            job("B 公司", "2025-01", "2025-03"),                       # 与 A 相隔 7 个月
            job("C 公司", "2025-02", None, present=True),               # 与 B 重叠 1 个月，至今
            job("学生会", "2024-03", "2025-12", kind="campus"),          # 校园经历不参与
            job("D 公司", "2023", "2024")]                              # 只有年份精度，跳过
    found = [f for f in _run(doc, {"work": work}) if f.rule_code == "TIMELINE_ANOMALY"]
    assert [f.title for f in found] == ["经历之间有 7 个月空窗", "经历时间重叠"]
    assert found[0].evidence_quote.startswith("B 公司") and found[1].evidence_quote.startswith("C 公司")
    assert "A 公司" in found[0].description and "1 个月重叠" in found[1].description


def test_ats_and_length():
    doc = Doc()
    p = _project(doc, "P", "将 QPS 从 200 提升至 1500，" + "并持续优化各个模块的细节，" * 12, "上线 3 次")
    findings = _run(doc, {"projects": [p]}, ats_signals={"images": 1, "textboxes": 0, "drawings": 2}, page_count=3)
    by_code = {}
    for f in findings:
        by_code.setdefault(f.rule_code, []).append(f)

    assert "图片 1 个、绘图对象 2 个" in by_code["ATS_UNFRIENDLY"][0].description
    assert by_code["ATS_UNFRIENDLY"][0].char_start is None and by_code["ATS_UNFRIENDLY"][0].category == "ats"
    titles = [f.title for f in by_code["LENGTH_ANOMALY"]]
    assert any("过长" in t for t in titles) and "单条描述过短" in titles and "简历共 3 页" in titles

    assert "ATS_UNFRIENDLY" not in _codes(_run(doc, {"projects": [p]}, ats_signals={"images": 0}))


def test_units_fall_back_to_the_whole_entry_and_include_summary():
    doc = Doc()
    entry = doc.add("某公司 实习 做了一些开发工作")
    summary = doc.add("踏实认真")
    units = iter_units({"work": [{"name": "某公司", **entry, "highlights": []}], "summary": summary}, doc.text)
    assert [(u.unit_id, u.unit_type, u.text) for u in units] == [
        ("work[0]", "work", "某公司 实习 做了一些开发工作"), ("summary", "summary", "踏实认真")]


# ───────────── 评分 ─────────────


def _f(category, severity, verify="exact"):
    return Finding(source="rule", category=category, severity=severity, title="", description="", suggestion="",
                   verify_result=verify)


def test_score_deducts_by_severity_and_weights_dimensions():
    overall, detail = score([_f("quantification", "high"), _f("quantification", "medium"), _f("expression", "low")])
    assert detail == {"completeness": 100.0, "quantification": 63.0, "expression": 95.0, "consistency": 100.0, "ats": 100.0}
    assert overall == round(0.25 * 100 + 0.25 * 63 + 0.20 * 95 + 0.20 * 100 + 0.10 * 100, 1)


def test_score_floors_at_zero_and_ignores_unverified_findings():
    overall, detail = score([_f("ats", "high")] * 6 + [_f("expression", "high", verify="failed")])
    assert detail["ats"] == 0.0 and detail["expression"] == 100.0 and overall == 90.0


def test_dimensions_nobody_checked_are_null_not_perfect():
    overall, detail = score([_f("expression", "medium")], mode="llm_only")
    assert detail == {"completeness": None, "quantification": None, "expression": 88.0, "consistency": 100.0, "ats": None}
    assert overall == 94.0                                          # 只在 expression 与 consistency 上加权
    assert score([], mode="rule_only")[0] == 100.0


def test_penalties_are_diluted_for_resumes_with_many_units():
    findings = [_f("expression", "medium")] * 8                     # 96 分的扣分
    assert score(findings, unit_count=4)[1]["expression"] == 4.0    # 基准以内不摊薄
    assert score(findings, unit_count=2)[1]["expression"] == 4.0    # 也不放大
    assert score(findings, unit_count=8)[1]["expression"] == 52.0   # 8 条经历 → 扣分减半