import pytest

from app.diagnose.evidence import locate_span, normalize_for_match

TEXT = (
    "项目经历\n"
    "二手电商交易平台 全栈开发 2024.01 - 2024.06\n"
    "负责优化系统性能，提升了响应速度。\n"
    "热点商品数据预热至 Redis，列表查询响应从 820ms 降至 140ms，DB 访问频次压降 60%。\n"
    "企业知识库智能问答助手 Agent开发 2024.07 - 2024.12\n"
    "负责优化系统性能，检索准确率明显提高。"
)


def _at(span):
    return TEXT[span.start:span.end]


def test_exact_match_returns_the_slice():
    span = locate_span("列表查询响应从 820ms 降至 140ms", TEXT)
    assert span.method == "exact" and span.score == 1.0
    assert _at(span) == "列表查询响应从 820ms 降至 140ms"


def test_hint_decides_which_occurrence():
    """同一句话在两个项目里各出现一次：必须定位到送审的那一条，而不是全文第一处。"""
    second_project = TEXT.index("企业知识库")
    span = locate_span("负责优化系统性能", TEXT, hint=(second_project, len(TEXT)))
    assert span.start > second_project and _at(span) == "负责优化系统性能"

    first = locate_span("负责优化系统性能", TEXT)
    assert first.start < second_project


def test_falls_back_to_full_text_when_not_in_hint():
    span = locate_span("DB 访问频次压降 60%", TEXT, hint=(0, 10))
    assert span is not None and _at(span) == "DB 访问频次压降 60%"


@pytest.mark.parametrize(
    "quote",
    [
        "热点商品数据预热至 Redis,列表查询响应从 820ms 降至 140ms",      # 全角逗号写成半角
        "热点商品数据预热至 redis，列表查询响应",                          # 大小写
        "“负责优化系统性能，提升了响应速度。”",                           # 模型给引用加了引号
        "  负责优化系统性能，提升了响应速度…",                            # 首尾空白与省略号
        "提升了响应速度。 热点商品数据预热至 Redis",                       # 跨块引用：原文是换行，模型写成空格
    ],
)
def test_formatting_differences_are_not_hallucinations(quote):
    span = locate_span(quote, TEXT)
    assert span is not None and span.method == "exact"
    assert normalize_for_match(_at(span)) == normalize_for_match(quote.strip(" \t\r\n\"'“”‘’…."))


def test_small_edits_are_located_by_fuzzy_alignment():
    span = locate_span("热点商品数据预热到 Redis，列表查询的响应从 820ms 降至 140ms", TEXT)  # 改了两个字
    assert span is not None and span.method == "fuzzy" and 0.9 <= span.score < 1.0
    assert "820ms 降至 140ms" in _at(span)


@pytest.mark.parametrize(
    "quote",
    [
        "将 QPS 从 200 提升至 1500，支撑双十一大促流量",   # 完全捏造
        "主导了微服务架构的整体设计与落地",
        "性能",                                             # 太短且……其实存在：见下一个用例
    ],
)
def test_fabricated_quotes_are_rejected(quote):
    span = locate_span(quote, TEXT)
    if quote == "性能":
        assert span is not None and span.method == "exact"   # 短引用只接受精确匹配
    else:
        assert span is None


def test_short_quotes_never_match_fuzzily():
    assert locate_span("性龙", TEXT) is None
    assert locate_span("x", TEXT) is None and locate_span("", TEXT) is None


def test_quote_longer_than_hint_window_still_checked_against_full_text():
    hint = (TEXT.index("负责优化"), TEXT.index("负责优化") + 5)
    span = locate_span("负责优化系统性能，提升了响应速度", TEXT, hint=hint)
    assert span is not None and _at(span) == "负责优化系统性能，提升了响应速度"


def test_normalization_is_length_preserving():
    raw = "ＡＢＣ，。！？【】《》“”‘’—～\n\t　ABCxyz 中文"
    assert len(normalize_for_match(raw)) == len(raw)
    assert normalize_for_match("ＡＢ，Ｃ") == "ab,c"
