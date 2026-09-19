"""版面分析：把 extract.py 抽出的"行"重建成正确的阅读顺序，并切成块、拼出 full_text。

算法（region-first，递归 XY 切分的一个变体）：对一个区域
  1. 找栏间空白带：用宽度 = 3% 页宽的竖直窗口滑过区域，取"挡住它的行最少"的位置。
       c = 1 − 挡住的行数 / 区域行数
     · c = 1            → 干净的空白带，直接左右切开（X 切），先读左栏再读右栏
     · 0.8 ≤ c < 1      → 少数行压住了空白带，它们是"跨栏行"（通栏标题、页顶姓名）；
                           用跨栏行把区域横切成几段，每段再各自处理
     · 0.3 < c < 0.8    → 说不清是不是两栏 → 标记 unknown，交给上层决定是否让 LLM 兜底
     · 其余             → 单栏
     空白带两侧都必须是"真正的一栏"（行数与字数够多），否则右对齐的日期会被误判成右栏。
  2. 切不动时，在足够大的水平留白处横切（Y 切），每段再试一次第 1 步。
  3. 仍切不动 → 叶子：同一水平线上的片段合并成一行，按 y 再按 x 排序。

之后在叶子内把"折行"并回同一块，遇到项目符号 / 标题 / 明显留白则另起一块。
最后 full_text = "\\n".join(block.text)，并固定每块的字符偏移（此后任何地方不得再改动文本）。

领域层：纯函数，不碰数据库，不调任何 API。
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from app.config import settings
from app.parser.extract import ExtractResult, Line, PageInfo

MIN_SIDE_LINES = 3        # 空白带每一侧至少要有这么多行，才算"一栏"
MIN_SIDE_CHAR_RATIO = 0.12  # 每一侧的字数至少占区域的这个比例（挡掉右对齐日期这类假右栏）
GRID_STEP = 2.0           # 滑动窗口步长（pt）
Y_CUT_FACTOR = 1.5        # 水平留白 ≥ 1.5 倍行高才横切
MAX_DEPTH = 6

_BULLET = re.compile(r"^(?:[•·▪■◆●○◦*➢➤►▶✓☑\-–—]|\d{1,2}[.、)）]|[（(]\d{1,2}[)）]|[①-⑩])\s*")
_PAGE_NO = re.compile(r"^\s*(?:第?\s*\d+\s*页?|\d+\s*/\s*\d+|-\s*\d+\s*-|Page\s*\d+(?:\s*of\s*\d+)?)\s*$", re.I)


@dataclass(slots=True)
class Block:
    block_index: int
    page_no: int
    column_index: int  # 0 = 左栏/单栏，1 = 右栏，-1 = 跨栏行
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    font_size: float
    is_bold: bool
    char_start: int = 0
    char_end: int = 0


@dataclass(slots=True)
class PageLayout:
    page_no: int
    layout_type: str  # single / double / sidebar / unknown
    confidence: float
    gap: tuple[float, float] | None


@dataclass(slots=True)
class LayoutResult:
    blocks: list[Block]
    full_text: str
    pages: list[PageLayout]

    @property
    def layout_type(self) -> str:
        return self.pages[0].layout_type if self.pages else "unknown"

    @property
    def layout_confidence(self) -> float:
        return min((p.confidence for p in self.pages), default=0.0)

    @property
    def needs_llm_fallback(self) -> bool:
        return self.layout_confidence < settings.LAYOUT_FALLBACK_CONF


@dataclass(slots=True)
class _Placed:
    line: Line
    col: int
    leaf: int
    leaf_x0: float
    leaf_x1: float
    tabular: bool = False  # 该行由相隔较远的多个片段拼成（如「项目名 …… 日期」），不是一句被折断的话


@dataclass(slots=True)
class _PageStats:
    total: int = 0
    in_columns: int = 0
    unknown: int = 0
    cut_c: list[float] = field(default_factory=list)
    leaf_c: list[float] = field(default_factory=list)
    gap: tuple[float, float] | None = None
    gap_lines: int = 0
    leaf_seq: int = 0


# ───────────────────────── 空白带搜索 ─────────────────────────


def _best_band(lines: list[Line], page_width: float) -> tuple[float, float, set[int], float] | None:
    """返回 (band_x0, band_x1, 挡住空白带的行下标集合, c)；没有合格的空白带返回 None。"""
    n = len(lines)
    if n < 2 * MIN_SIDE_LINES:
        return None
    width = settings.LAYOUT_MIN_GAP_RATIO * page_width
    lo = min(l.x0 for l in lines)
    hi = max(l.x1 for l in lines)
    total_chars = sum(len(l.text) for l in lines) or 1
    eps = 0.5

    best: tuple[int, float, float, set[int]] | None = None  # (挡住数, 不平衡度, a, U)
    a = lo
    while a + width <= hi:
        b = a + width
        blocked = {i for i, l in enumerate(lines) if l.x0 < b - eps and l.x1 > a + eps}
        left = [l for l in lines if l.x1 <= a + eps]
        right = [l for l in lines if l.x0 >= b - eps]
        if len(left) >= MIN_SIDE_LINES and len(right) >= MIN_SIDE_LINES:
            lc = sum(len(l.text) for l in left) / total_chars
            rc = sum(len(l.text) for l in right) / total_chars
            if lc >= MIN_SIDE_CHAR_RATIO and rc >= MIN_SIDE_CHAR_RATIO:
                key = (len(blocked), abs(lc - rc))
                if best is None or key < (best[0], best[1]):
                    best = (len(blocked), abs(lc - rc), a, blocked)
        a += GRID_STEP
    if best is None:
        return None

    _, _, a, blocked = best
    # 在不增加"挡住的行"的前提下，把窗口向两侧扩到最宽，得到真实的空白带
    free = [l for i, l in enumerate(lines) if i not in blocked]
    band_x0 = max((l.x1 for l in free if l.x1 <= a + eps), default=a)
    band_x1 = min((l.x0 for l in free if l.x0 >= a + width - eps), default=a + width)
    return band_x0, band_x1, blocked, 1 - len(blocked) / n


def _header_rows_above_right_column(lines: list[Line], band_x1: float, page_width: float) -> set[int]:
    """页顶居中的联系方式（电话 / 邮箱分居空白带两侧但都没压住它）不属于任何一栏。

    右栏的行大多左对齐在同一条竖线上；整行都位于"右栏第一条对齐行"上方的，视为页顶通栏内容。
    """
    right = [l for l in lines if l.x0 >= band_x1 - 0.5]
    if len(right) < MIN_SIDE_LINES:
        return set()
    edges = [round(l.x0 / 4) * 4 for l in right]
    mode = max(set(edges), key=edges.count)
    aligned = [l for l in right if abs(l.x0 - mode) <= 0.02 * page_width]
    top = min(l.y0 for l in aligned)
    return {i for i, l in enumerate(lines) if l.y1 <= top}


# ───────────────────────── 递归切分 ─────────────────────────


def _rows(lines: list[Line]) -> list[list[Line]]:
    """按垂直重叠把片段分到同一水平行。"""
    rows: list[list[Line]] = []
    for l in sorted(lines, key=lambda l: (l.y0, l.x0)):
        if rows:
            ref = rows[-1][0]
            overlap = min(ref.y1, l.y1) - max(ref.y0, l.y0)
            if overlap >= 0.5 * min(ref.height, l.height):
                rows[-1].append(l)
                continue
        rows.append([l])
    return rows


def _merge_row(row: list[Line]) -> Line:
    row = sorted(row, key=lambda l: l.x0)
    if len(row) == 1:
        return row[0]
    main = max(row, key=lambda l: len(l.text))
    chars = sum(len(l.text) for l in row)
    bold = sum(len(l.text) for l in row if l.is_bold)
    return Line(
        page_no=row[0].page_no,
        x0=min(l.x0 for l in row), y0=min(l.y0 for l in row),
        x1=max(l.x1 for l in row), y1=max(l.y1 for l in row),
        text=" ".join(l.text for l in row),
        font_size=main.font_size,
        is_bold=bold * 2 > chars,
    )


def _is_tabular(row: list[Line]) -> bool:
    row = sorted(row, key=lambda l: l.x0)
    return any(b.x0 - a.x1 > 2 * a.font_size for a, b in zip(row, row[1:]))


def _leaf(lines: list[Line], col: int | None, stats: _PageStats) -> list[_Placed]:
    stats.leaf_seq += 1
    rows = _rows(lines)
    merged = [_merge_row(r) for r in rows]
    x0, x1 = min(l.x0 for l in merged), max(l.x1 for l in merged)
    return [_Placed(l, 0 if col is None else col, stats.leaf_seq, x0, x1, _is_tabular(r))
            for l, r in zip(merged, rows)]


def _y_segments(lines: list[Line]) -> list[list[Line]]:
    rows = _rows(lines)
    if len(rows) < 2:
        return [lines]
    threshold = Y_CUT_FACTOR * statistics.median(l.height for l in lines)
    segments: list[list[Line]] = [list(rows[0])]
    bottom = max(l.y1 for l in rows[0])
    for row in rows[1:]:
        if min(l.y0 for l in row) - bottom >= threshold:
            segments.append([])
        segments[-1].extend(row)
        bottom = max(bottom, max(l.y1 for l in row))
    return segments


def _order(lines: list[Line], page_width: float, col: int | None, stats: _PageStats,
           depth: int = 0, allow_y: bool = True) -> list[_Placed]:
    if not lines:
        return []
    band = _best_band(lines, page_width) if depth < MAX_DEPTH else None

    if band and band[3] >= settings.LAYOUT_DOUBLE_MIN_C:
        band_x0, band_x1, blocked, c = band
        spanning = blocked | _header_rows_above_right_column(lines, band_x1, page_width)
        stats.cut_c.append(c)
        body = len(lines) - len(spanning)
        if body > stats.gap_lines:
            stats.gap, stats.gap_lines = (round(band_x0, 1), round(band_x1, 1)), body

        if not spanning:
            left = [l for l in lines if l.x1 <= band_x0 + 0.5]
            right = [l for l in lines if l.x0 >= band_x1 - 0.5]
            stats.in_columns += len(lines)
            return (_order(left, page_width, 0 if col is None else col, stats, depth + 1)
                    + _order(right, page_width, 1 if col is None else col, stats, depth + 1))

        # 有跨栏行：按 y 把区域横切成段，跨栏行自成一段
        placed: list[_Placed] = []
        segment: list[Line] = []
        span_rows: list[Line] = []

        def flush_segment() -> None:
            if segment:
                placed.extend(_order(list(segment), page_width, col, stats, depth + 1))
                segment.clear()

        def flush_span() -> None:
            if span_rows:
                stats.leaf_seq += 1
                for l in (_merge_row(r) for r in _rows(span_rows)):
                    placed.append(_Placed(l, -1 if col is None else col, stats.leaf_seq, l.x0, l.x1))
                span_rows.clear()

        for i, l in sorted(enumerate(lines), key=lambda t: (t[1].y0, t[1].x0)):
            if i in spanning:
                flush_segment()
                span_rows.append(l)
            else:
                flush_span()
                segment.append(l)
        flush_segment()
        flush_span()
        return placed

    if allow_y:
        segments = _y_segments(lines)
        if len(segments) > 1:
            out: list[_Placed] = []
            for seg in segments:
                out.extend(_order(seg, page_width, col, stats, depth + 1, allow_y=False))
            return out

    c = band[3] if band else 0.0
    stats.leaf_c.append(c)
    if settings.LAYOUT_SINGLE_MAX_C < c < settings.LAYOUT_DOUBLE_MIN_C:
        stats.unknown += len(lines)
    return _leaf(lines, col, stats)


# ───────────────────────── 页眉页脚 ─────────────────────────


def _drop_headers_footers(lines: list[Line], pages: list[PageInfo]) -> list[Line]:
    height = {p.page_no: p.height for p in pages}
    ratio = settings.LAYOUT_HEADER_FOOTER_RATIO

    def in_margin(l: Line) -> bool:
        h = height[l.page_no]
        return l.y1 <= ratio * h or l.y0 >= (1 - ratio) * h

    repeated: dict[tuple[str, int], set[int]] = {}
    for l in lines:
        if in_margin(l):
            repeated.setdefault((l.text, round(l.y0 / 4)), set()).add(l.page_no)

    def is_noise(l: Line) -> bool:
        if not in_margin(l):
            return False
        return bool(_PAGE_NO.match(l.text)) or len(repeated[(l.text, round(l.y0 / 4))]) >= 2

    return [l for l in lines if not is_noise(l)]


# ───────────────────────── 行 → 块 ─────────────────────────


def _join(prev: str, nxt: str) -> str:
    """折行拼回一句：中文之间不加空格，英文 / 数字之间补一个空格。"""
    if prev and nxt and prev[-1].isascii() and nxt[0].isascii() and prev[-1] != " ":
        return prev + " " + nxt
    return prev + nxt


def _to_blocks(placed: list[_Placed], body_size: float) -> list[Block]:
    def heading_like(l: Line) -> bool:
        return l.font_size >= body_size + 1 or (l.is_bold and len(l.text) <= 20)

    blocks: list[Block] = []
    prev: _Placed | None = None
    for p in placed:
        l = p.line
        new_block = (
            prev is None
            or p.leaf != prev.leaf
            or l.page_no != prev.line.page_no
            or _BULLET.match(l.text) is not None
            or heading_like(l)
            or heading_like(prev.line)
            or l.font_size != prev.line.font_size
            or l.is_bold != prev.line.is_bold
            or l.y0 - prev.line.y1 > 0.7 * l.height
            or prev.tabular
            # 上一行没写满就换行了 → 它是完整的一条，不是折行
            # 容差：英文按词折行，行尾可能空出一个长单词的宽度
            or prev.line.x1 < prev.leaf_x1 - max(2.5 * prev.line.font_size, 0.08 * (prev.leaf_x1 - prev.leaf_x0))
        )
        if new_block:
            blocks.append(Block(len(blocks), l.page_no, p.col, l.x0, l.y0, l.x1, l.y1,
                                l.text, l.font_size, l.is_bold))
        else:
            b = blocks[-1]
            b.text = _join(b.text, l.text)
            b.x0, b.y0 = min(b.x0, l.x0), min(b.y0, l.y0)
            b.x1, b.y1 = max(b.x1, l.x1), max(b.y1, l.y1)
        prev = p
    return blocks


# ───────────────────────── 入口 ─────────────────────────


def analyze_layout(extracted: ExtractResult) -> LayoutResult:
    lines = _drop_headers_footers(extracted.lines, extracted.pages)
    sizes = sorted(l.font_size for l in lines for _ in range(len(l.text)))
    body_size = sizes[len(sizes) // 2] if sizes else 10.5

    placed: list[_Placed] = []
    pages: list[PageLayout] = []
    leaf_offset = 0
    for page in extracted.pages:
        page_lines = [l for l in lines if l.page_no == page.page_no]
        stats = _PageStats(total=len(page_lines), leaf_seq=leaf_offset)
        placed.extend(_order(page_lines, page.width, None, stats))
        leaf_offset = stats.leaf_seq
        pages.append(_summarize(page, stats))

    blocks = _to_blocks(placed, body_size)
    cursor = 0
    for b in blocks:
        b.char_start, b.char_end = cursor, cursor + len(b.text)
        cursor = b.char_end + 1  # 块之间以一个 "\n" 连接
    return LayoutResult(blocks, "\n".join(b.text for b in blocks), pages)


def _summarize(page: PageInfo, s: _PageStats) -> PageLayout:
    if s.total == 0:
        return PageLayout(page.page_no, "single", 1.0, None)
    if s.unknown / s.total >= 0.3:
        return PageLayout(page.page_no, "unknown", 0.5, None)
    if s.cut_c and s.gap and s.gap_lines / s.total >= 0.3:
        center = (s.gap[0] + s.gap[1]) / 2 / page.width
        kind = "double" if 0.4 <= center <= 0.6 else "sidebar"
        return PageLayout(page.page_no, kind, round(min(s.cut_c), 3), s.gap)
    confidence = 1 - max([c for c in s.leaf_c if c <= settings.LAYOUT_SINGLE_MAX_C], default=0.0)
    return PageLayout(page.page_no, "single", round(confidence, 3), None)
