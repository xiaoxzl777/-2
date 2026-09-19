import pytest

from app.parser.normalize import find_date_range, months_between


@pytest.mark.parametrize(
    ("text", "start", "end", "present"),
    [
        ("2023.09-2024.06", "2023-09", "2024-06", False),
        ("2023.9 - 2024.1", "2023-09", "2024-01", False),
        ("2023/09—2024/01", "2023-09", "2024-01", False),
        ("2023-09 ~ 2024-06", "2023-09", "2024-06", False),
        ("2023-09-2024-06", "2023-09", "2024-06", False),
        ("2023年9月至2024年6月", "2023-09", "2024-06", False),
        ("2023年9月 到 2024年1月", "2023-09", "2024-01", False),
        ("2023.09-至今", "2023-09", None, True),
        ("2023年9月至今", "2023-09", None, True),
        ("2023.07 – Present", "2023-07", None, True),
        ("Sep 2023 – Present", "2023-09", None, True),
        ("September 2023 - Jun. 2024", "2023-09", "2024-06", False),
        ("Sept 2022 to Dec 2022", "2022-09", "2022-12", False),
        ("2021-2023", "2021", "2023", False),                 # 纯年份：不能读成 2021 年 20 月
        ("2021年-2025年", "2021", "2025", False),
        ("2023.9-2024", "2023", "2024", False),               # 两端精度不一致 → 取粗的一端
        ("2022 - 2023.06", "2022", "2023", False),
        ("2023年", "2023", None, False),                      # 单个日期（如获奖年份）
        ("2024.05", "2024-05", None, False),
        ("2023", "2023", None, False),                       # 整段只有一个年份
    ],
)
def test_formats(text, start, end, present):
    r = find_date_range(text)
    assert r is not None, text
    assert (r.start, r.end, r.is_present) == (start, end, present)
    assert r.span == (0, len(text))


def test_finds_the_range_inside_a_line_and_reports_its_span():
    text = "东莞城市学院（全日制） 计算机科学与技术专业 (本科) 2022.09 - 2026.06"
    r = find_date_range(text)
    assert (r.start, r.end) == ("2022-09", "2026-06")
    assert text[r.span[0]:r.span[1]] == "2022.09 - 2026.06"
    assert r.month_precision


@pytest.mark.parametrize(
    "text",
    ["负责订单服务的开发", "QPS 从 200 提升到 1500", "电话 13800138000", "响应从 820ms 降至 140ms",
     "订单号 120231234", "Vue3 + Spring Boot 2.7", "支撑 2000 名用户同时在线", "日活 2023 人", ""],
)
def test_no_false_positives(text):
    assert find_date_range(text) is None


def test_year_precision_is_flagged():
    assert not find_date_range("2021-2023").month_precision
    assert find_date_range("2021.03-2023.04").month_precision


def test_months_between():
    assert months_between("2023-09", "2024-01") == 4
    assert months_between("2024-06", "2024-06") == 0
    assert months_between("2024-06", "2023-06") == -12
    assert months_between("2023", "2024-01") is None


def test_bare_year_needs_context_but_a_later_real_date_is_still_found():
    r = find_date_range("服务 2000 家客户，2023年获评优秀项目")
    assert r.start == "2023" and r.end is None
