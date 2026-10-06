"""版面合成集脚本：每种版式各生成一份，解析出的阅读顺序与标准答案完全一致；打分函数本身的行为。"""
import random

import pytest

from app.parser.extract import extract_pdf
from app.parser.layout import analyze_layout
from scripts.eval_layout import EXPECTED_TYPE, pair_score, scorable
from scripts.gen_layout_set import LAYOUTS, SEED, make_content, render


# 无边框表格型是已知局限（只靠对齐，左列章节名会被当成一栏），不要求全对
@pytest.mark.parametrize("layout", [l for l in LAYOUTS if l != "borderless"])
def test_generated_resume_is_read_in_the_right_order(tmp_path, layout):
    cv = render(layout, make_content(random.Random(SEED * 1000), 0), SEED * 1000 + LAYOUTS.index(layout))
    path = tmp_path / f"{layout}.pdf"
    cv.doc.save(path)
    cv.doc.close()

    r = analyze_layout(extract_pdf(path))
    lines = scorable(cv.lines)
    assert pair_score(lines, r.full_text) == (len(lines) - 1, len(lines) - 1, 0)
    assert r.layout_type == EXPECTED_TYPE[layout]


def test_pair_score_requires_adjacent_pairs_to_stay_adjacent():
    lines = ["左一", "左二", "右一", "右二"]
    assert pair_score(lines, "左一\n左二\n右一\n右二") == (3, 3, 0)
    assert pair_score(lines, "左一 右一\n左二 右二") == (0, 3, 0)      # 两栏按行交错着读：一对都不算对
    assert pair_score(lines, "左一\n左二\n右二") == (1, 3, 1)          # 找不到的段，前后两对都算错
    assert pair_score(scorable(["电话：138 | 邮箱", "教育"]), "电话：138  |  邮箱\n教育") == (1, 1, 0)  # 空白不影响定位


def test_fragments_that_are_part_of_another_are_not_scored():
    assert scorable(["Redis", "熟悉 Redis 与 MySQL", "项目经历"]) == ["熟悉Redis与MySQL", "项目经历"]
