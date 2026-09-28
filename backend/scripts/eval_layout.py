"""版面合成集评测：python scripts/eval_layout.py（先跑 scripts/gen_layout_set.py 生成数据）

指标（05-evaluation-and-plan 8.2）：
  相邻行对顺序准确率：标准答案里前后相邻的两段文字，在输出里也紧挨着、且顺序一样的比例（所有文档的相邻对一起算）。
                      只看"前一段在前"太宽松：两栏按行交错着读，栏内的相邻对仍然"在前"，几乎不扣分
  文档级全对率：所有相邻对都对的文档占比
  版面判对率：analyze_layout 判出的版面类型和生成时的版式一致的占比（只对本系统算）
对照：
  pymupdf_sort    PyMuPDF 自带的 get_text(sort=True)：按坐标从上到下、从左到右
  ours_no_table   本系统，但去掉表格识别（相当于加表格识别之前的版本）
  ours            本系统（analyze_layout 的 full_text）
一段文字在输出里用 str.find 定位，定位前两边都去掉空白（PyMuPDF 会把"两个空格 + 中文"压成一个空格，
这是文字规整上的差别，不该算成顺序错）；标准答案里是别的段的子串的段不参与计分（定位不唯一）。
结果打印成表，并写一份 JSON 到 data/eval_runs/。
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import pymupdf

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.parser.extract import extract_pdf  # noqa: E402
from app.parser.layout import analyze_layout  # noqa: E402
from scripts.gen_layout_set import LAYOUTS, OUT_DIR  # noqa: E402

METHODS = ("pymupdf_sort", "ours_no_table", "ours")


def read_text(path: Path, method: str) -> tuple[str, str | None]:
    """返回（输出文本，判出的版面类型；PyMuPDF 不判版面时为 None）。"""
    if method == "pymupdf_sort":
        with pymupdf.open(path) as doc:
            return "\n".join(page.get_text("text", sort=True) for page in doc), None
    extracted = extract_pdf(path)
    if method == "ours_no_table":
        extracted.tables = []
    layout = analyze_layout(extracted)
    return layout.full_text, layout.layout_type


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def scorable(lines: list[str]) -> list[str]:
    """去掉空白；再去掉是别的段的子串的段：它们在输出里的位置定不唯一。"""
    lines = [squash(s) for s in lines]
    return [s for i, s in enumerate(lines) if not any(i != j and s in t for j, t in enumerate(lines))]


def pair_score(lines: list[str], text: str) -> tuple[int, int, int]:
    """（顺序对的相邻对数，相邻对总数，输出里找不到的段数）。找不到的段所在的相邻对都算错。"""
    text = squash(text)
    pos = [text.find(s) for s in lines]
    found = sorted((p, i) for i, p in enumerate(pos) if p >= 0)
    following = {i: j for (_, i), (_, j) in zip(found, found[1:])}  # 输出里紧跟在第 i 段后面的是第几段
    ok = sum(1 for i in range(len(lines) - 1) if following.get(i) == i + 1)
    return ok, len(lines) - 1, sum(1 for p in pos if p < 0)


def main() -> None:
    gt = json.loads((OUT_DIR / "gt.json").read_text(encoding="utf-8"))
    # stats[method][layout] = [顺序对的相邻对, 相邻对总数, 全对的文档数, 文档数, 找不到的段, 版面判对的文档数]
    stats: dict[str, dict[str, list[int]]] = {m: defaultdict(lambda: [0] * 6) for m in METHODS}
    started = time.perf_counter()
    for name, doc in gt.items():
        lines = scorable(doc["lines"])
        for method in METHODS:
            text, layout_type = read_text(OUT_DIR / name, method)
            ok, total, missing = pair_score(lines, text)
            for key in (doc["layout"], "all"):
                s = stats[method][key]
                s[0] += ok
                s[1] += total
                s[2] += ok == total
                s[3] += 1
                s[4] += missing
                s[5] += layout_type == doc["layout"]

    groups = list(LAYOUTS) + ["all"]
    print(f"{len(gt)} 份，用时 {time.perf_counter() - started:.1f}s\n")
    print("相邻行对顺序准确率 / 文档级全对率")
    print(f"{'':<16}" + "".join(f"{g:>20}" for g in groups))
    for method in METHODS:
        cells = [f"{s[0] / s[1]:.2%} / {s[2]}/{s[3]}" for s in (stats[method][g] for g in groups)]
        print(f"{method:<16}" + "".join(f"{c:>20}" for c in cells))
    missing = {m: stats[m]["all"][4] for m in METHODS}
    print(f"\n输出里找不到的段：{missing}")
    print("版面判对率（ours）：" + "  ".join(
        f"{g} {stats['ours'][g][5]}/{stats['ours'][g][3]}" for g in groups))

    report = {m: {g: dict(zip(["pairs_ok", "pairs", "docs_ok", "docs", "missing", "layout_ok"], stats[m][g]))
                  for g in groups} for m in METHODS}
    out = settings.DATA_DIR / "eval_runs" / f"layout-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n结果已写入 {out}")


if __name__ == "__main__":
    main()
