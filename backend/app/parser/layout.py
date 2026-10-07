"""版面分析：把 extract.py 抽出的"行"重建成正确的阅读顺序，并切成块、拼出 full_text。

算法（region-first，递归 XY 切分的一个变体）：
  0. 表格：extract 找到的带边框表格，把落在里面的行归到各个格子，整张表缩成一个"替身行"参与下面的分栏
     （压住中缝就是通栏，落在某一栏里就留在那一栏）；排好位置后再按行展开，见 _place_table。
     否则表格的列间空白会被当成栏间空白，整张表按列读乱。
  对一个区域
  1. 找栏间空白带：用宽度 = 3% 页宽的竖直窗口滑过区域，取"挡住它的行最少"的位置。
       c = 1 − 挡住的行数 / 区域行数
     · c = 1            → 干净的空白带，直接左右切开（X 切），先读左栏再读右栏
     · 0.8 ≤ c < 1      → 少数行压住了空白带，它们是"跨栏行"（通栏标题、页顶姓名）；
                           用跨栏行把区域横切成几段，每段再各自处理
     · 0.3 < c < 0.8    → 说不清是不是两栏 → 标记 unknown，按行读（不做模型兜底，见 docs/04-design 5.1）
     · 其余             → 单栏
     空白带两侧都必须是"真正的一栏"（行数与字数够多），否则右对齐的日期会被误判成右栏。
     较少的一侧过半是日期、且这些日期都和另一侧某一行在同一水平线上 → 时间轴版式（左列日期、右边经历），
     不切：按行读，日期跟着它那条经历。否则会先读完所有日期再读经历，而且置信度还是 1.0。
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
from app.parser.extract import Box, ExtractResult, Line, PageInfo, TableBox
from app.parser.normalize import find_date_range

# ── 分栏 ──
MIN_SIDE_LINES = 3            # 空白带每一侧至少要有这么多行，才算"一栏"
MIN_SIDE_CHAR_RATIO = 0.12    # 每一侧的字数至少占区域的这个比例（挡掉右对齐日期这类假右栏）
GRID_STEP = 2.0               # 滑动窗口步长（pt）
EDGE_EPS = 0.5                # 判断"在空白带一侧"时的坐标容差（pt）
Y_CUT_FACTOR = 1.5            # 水平留白 ≥ 1.5 倍行高才横切
MAX_DEPTH = 6                 # 递归深度上限
COLUMN_PAGE_RATIO = 0.3       # 分栏 / unknown 的行数占全页比例达到这个值，才据此给整页定性
DATE_COLUMN_RATIO = 0.8       # 时间轴的日期列：较少一侧过半是日期，且其中至少这么多和另一侧同一行

# ── 表格 ──
TABLE_MIN_FILLED = 4          # 至少这么多格子有字才算表格：也挡掉"顶部色条 + 侧边栏底色块"拼成的假表格
LABEL_MAX_LEN = 8             # 只有两格的行，左格不超过这么多字 → 当成标签单独成块（表格型简历常把章节名放在左列）

# ── 分块 ──
HEADING_EXTRA_SIZE = 1.0      # 字号比正文大这么多 → 像标题
HEADING_MAX_LEN = 20          # 加粗且不超过这么多字 → 像标题
PARAGRAPH_GAP = 0.7           # 行间留白超过 0.7 倍行高 → 新段落
TABULAR_GAP = 2.0             # 同一行内两个片段相隔超过 2 倍字号 → 表格式的行（如「项目名 …… 日期」）
WRAP_SLACK_EM = 2.5           # 行尾距栏右边界不超过 2.5 个字宽，才算"写满了所以折行"
WRAP_SLACK_RATIO = 0.08       # …或不超过栏宽的 8%（英文按词折行，行尾会空出一个长单词）

_BULLET = re.compile(r"^(?:[•·▪■◆●○◦*➢➤►▶✓☑\-–—]|\d{1,2}[.、)）]|[（(]\d{1,2}[)）]|[①-⑩])\s*")
# "缓存与分布式：熟练使用 Redis…" 这种"短标签 + 冒号"开头的行；纯数字（10:30）与网址（http://）不算
_LABEL = re.compile(r"^(?!\d+[：:])(?![A-Za-z]+://)[^\s：:，。、,；;()（）]{2,16}[：:]")
_PAGE_NO = re.compile(r"^\s*(?:第?\s*\d+\s*页?|\d+\s*/\s*\d+|-\s*\d+\s*-|Page\s*\d+(?:\s*of\s*\d+)?)\s*$", re.I)


# ───────────────────────── 对外的数据结构 ─────────────────────────


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


# ───────────────────────── 内部数据结构 ─────────────────────────


@dataclass(slots=True)
class _Band:
    """一条候选的栏间空白带。"""

    x0: float
    x1: float
    blocked: set[int]   # 压住这条空白带的行（在区域内的下标）
    clearness: float    # 即文档里的 c：1 − 压住的行数 / 区域行数


@dataclass(slots=True)
class _Placed:
    """一行文字，连同它在版面里的归属。"""

    line: Line
    col: int
    leaf: int           # 所属叶子区域的编号；折行只在同一叶子内合并
    leaf_x0: float
    leaf_x1: float
    tabular: bool = False  # 由相隔较远的多个片段拼成（如「项目名 …… 日期」），不是一句被折断的话


@dataclass(slots=True)
class _Cell:
    bbox: Box
    lines: list[Line] = field(default_factory=list)


@dataclass(slots=True)
class _Table:
    bbox: Box
    rows: list[list[_Cell]]   # 只留有字的格子；没有字的行整行去掉

    @property
    def lines(self) -> list[Line]:
        return [l for row in self.rows for c in row for l in c.lines]


@dataclass(slots=True)
class _TableLine(Line):
    """整张表在分栏时的替身：占住表格的位置，排好顺序后再展开。"""

    table: _Table | None = None


@dataclass(slots=True)
class _PageStats:
    """递归过程中顺手记下的统计，用来给整页定性、算置信度。"""

    total: int = 0
    chars: int = 0
    table_chars: int = 0
    unknown_lines: int = 0
    cut_clearness: list[float] = field(default_factory=list)
    leaf_clearness: list[float] = field(default_factory=list)
    main_gap: tuple[float, float] | None = None   # 覆盖行数最多的那条空白带
    main_gap_lines: int = 0
    leaf_seq: int = 0


@dataclass(slots=True)
class _Region:
    """递归时不变的上下文，省得每层都传一长串参数。"""

    page_width: float
    stats: _PageStats
    date_columns: bool = True   # 评测消融用：False 时不认日期列（最初的算法）


# ───────────────────────── 空白带搜索 ─────────────────────────


def _best_band(lines: list[Line], page_width: float) -> _Band | None:
    """滑动窗口找"被最少的行压住"的竖直空白带；两侧不成栏则返回 None。"""
    n = len(lines)
    if n < 2 * MIN_SIDE_LINES:
        return None
    width = settings.LAYOUT_MIN_GAP_RATIO * page_width
    total_chars = sum(len(l.text) for l in lines) or 1

    def char_share(side: list[Line]) -> float:
        return sum(len(l.text) for l in side) / total_chars

    best: tuple[tuple[int, float], float, set[int]] | None = None  # (排序键, 窗口左端, 压住的行)
    a = min(l.x0 for l in lines)
    right_end = max(l.x1 for l in lines)
    while a + width <= right_end:
        b = a + width
        left = [l for l in lines if l.x1 <= a + EDGE_EPS]
        right = [l for l in lines if l.x0 >= b - EDGE_EPS]
        if len(left) >= MIN_SIDE_LINES and len(right) >= MIN_SIDE_LINES:
            left_share, right_share = char_share(left), char_share(right)
            if min(left_share, right_share) >= MIN_SIDE_CHAR_RATIO:
                blocked = {i for i, l in enumerate(lines) if l.x0 < b - EDGE_EPS and l.x1 > a + EDGE_EPS}
                key = (len(blocked), abs(left_share - right_share))  # 压住的行越少越好，其次两侧越均衡越好
                if best is None or key < best[0]:
                    best = (key, a, blocked)
        a += GRID_STEP
    if best is None:
        return None

    _, a, blocked = best
    # 在不增加"压住的行"的前提下，把窗口向两侧扩到最宽，得到真实的空白带
    free = [l for i, l in enumerate(lines) if i not in blocked]
    x0 = max((l.x1 for l in free if l.x1 <= a + EDGE_EPS), default=a)
    x1 = min((l.x0 for l in free if l.x0 >= a + width - EDGE_EPS), default=a + width)
    return _Band(x0, x1, blocked, 1 - len(blocked) / n)


def _is_date_line(text: str) -> bool:
    """这一行主要就是一个日期 / 时间段（「2023.07-2023.09」「2024.05 - 至今」），不是正文里碰巧带个年份。"""
    found = find_date_range(text)
    return found is not None and found.span[1] - found.span[0] >= 0.5 * len(text.strip())


def _is_date_column(lines: list[Line], band: _Band) -> bool:
    """空白带较少的一侧是不是时间轴的日期列：一半以上是日期，且这些日期几乎都和另一侧某一行在同一水平线上。

    "一半以上"而不是"全是"：日期列里还夹着「教育背景」这类短标题（它们不跨过空白带，也不和另一侧对齐）。
    只看"两侧对不对齐"不够：正常的两栏、侧边栏行距一样，左右也常常对得很齐（合成集里最高 0.94）。
    """
    left = [l for l in lines if l.x1 <= band.x0 + EDGE_EPS]
    right = [l for l in lines if l.x0 >= band.x1 - EDGE_EPS]
    small, other = sorted((left, right), key=len)

    def same_row(a: Line, b: Line) -> bool:
        return abs((a.y0 + a.y1) - (b.y0 + b.y1)) / 2 <= 0.5 * min(a.height, b.height)

    dates = [s for s in small if _is_date_line(s.text)]
    aligned = [s for s in dates if any(same_row(s, o) for o in other)]
    return bool(dates) and len(dates) >= 0.5 * len(small) and len(aligned) >= DATE_COLUMN_RATIO * len(dates)


def _header_rows_above_right_column(lines: list[Line], band: _Band, page_width: float) -> set[int]:
    """页顶居中的联系方式（电话 / 邮箱分居空白带两侧但都没压住它）不属于任何一栏。

    右栏的行大多左对齐在同一条竖线上；整行都位于"右栏第一条对齐行"上方的，视为页顶通栏内容。
    """
    right = [l for l in lines if l.x0 >= band.x1 - EDGE_EPS]
    if len(right) < MIN_SIDE_LINES:
        return set()
    edges = [round(l.x0 / 4) * 4 for l in right]
    column_edge = max(set(edges), key=edges.count)
    aligned = [l for l in right if abs(l.x0 - column_edge) <= 0.02 * page_width]
    column_top = min(l.y0 for l in aligned)
    return {i for i, l in enumerate(lines) if l.y1 <= column_top}


# ───────────────────────── 行的合并 ─────────────────────────


def _rows(lines: list[Line]) -> list[list[Line]]:
    """按垂直重叠把片段分到同一水平行。表格替身自成一行，不和旁边的文字合并。"""
    rows: list[list[Line]] = []
    for l in sorted(lines, key=lambda l: (l.y0, l.x0)):
        if rows and not isinstance(l, _TableLine) and not isinstance(rows[-1][0], _TableLine):
            ref = rows[-1][0]
            overlap = min(ref.y1, l.y1) - max(ref.y0, l.y0)
            if overlap >= 0.5 * min(ref.height, l.height):
                rows[-1].append(l)
                continue
        rows.append([l])
    return rows


def _union(lines: list[Line], text: str) -> Line:
    """几段文字拼成一行：外框取并集，字号取最长那段的，加粗看字数过半。"""
    longest = max(lines, key=lambda l: len(l.text))
    chars = sum(len(l.text) for l in lines)
    bold_chars = sum(len(l.text) for l in lines if l.is_bold)
    return Line(
        page_no=lines[0].page_no,
        x0=min(l.x0 for l in lines), y0=min(l.y0 for l in lines),
        x1=max(l.x1 for l in lines), y1=max(l.y1 for l in lines),
        text=text,
        font_size=longest.font_size,
        is_bold=bold_chars * 2 > chars,
    )


def _merge_row(row: list[Line]) -> Line:
    """同一水平线上的片段（如「电话    邮箱」）合并成一行，片段之间补一个空格。"""
    row = sorted(row, key=lambda l: l.x0)
    if len(row) == 1:
        return row[0]
    return _union(row, " ".join(l.text for l in row))


def _is_tabular(row: list[Line]) -> bool:
    row = sorted(row, key=lambda l: l.x0)
    return any(b.x0 - a.x1 > TABULAR_GAP * a.font_size for a, b in zip(row, row[1:]))


def _place_rows(lines: list[Line], col: int, stats: _PageStats,
                bounds: tuple[float, float] | None = None) -> list[_Placed]:
    """把一组行作为一个叶子区域落位：合并同行片段，按 y、x 排序；遇到表格替身就地展开。

    bounds 是叶子的左右边界（判断"这一行写满了没有"用），默认取这些行自己的范围；表格的格子传格子的边框。
    """
    stats.leaf_seq += 1
    leaf = stats.leaf_seq
    rows = _rows(lines)
    merged = [None if isinstance(r[0], _TableLine) else _merge_row(r) for r in rows]
    text = [l for l in merged if l is not None]
    x0, x1 = bounds or (min((l.x0 for l in text), default=0.0), max((l.x1 for l in text), default=0.0))
    placed: list[_Placed] = []
    for r, l in zip(rows, merged):
        if l is None:
            placed.extend(_place_table(r[0].table, col, stats))
        else:
            placed.append(_Placed(l, col, leaf, x0, x1, _is_tabular(r)))
    return placed


def _place_table(table: _Table, col: int, stats: _PageStats) -> list[_Placed]:
    """按行展开一张表，一行里的格子从左到右：
      · 每格都只有一行字 → 整行一块，格与格之间空一格（「时间 学校 专业」「姓名 张三 性别 男」）；
        第一格是标签时先单独成块（「获奖情况 | 蓝桥杯省二等奖」：左列多半是章节名，拆开才认得出）；
      · 有格子写了多行 → 每格各自是一个叶子，照常拼折行、按项目符号分块（「项目经历 | 多行描述」）。
    每一块都在自己的叶子里，不会和表格外、别的格子里的行拼成一块。
    """
    placed: list[_Placed] = []

    def add(parts: list[Line]) -> None:
        line = parts[0] if len(parts) == 1 else _union(parts, " ".join(p.text for p in parts))
        stats.leaf_seq += 1
        placed.append(_Placed(line, col, stats.leaf_seq, line.x0, line.x1, len(parts) > 1))

    for row in table.rows:
        cells = sorted(row, key=lambda c: c.bbox[0])
        visual = [_rows(c.lines) for c in cells]
        if any(len(v) > 1 for v in visual):
            for c in cells:
                placed.extend(_place_rows(c.lines, col, stats, bounds=(c.bbox[0], c.bbox[2])))
            continue
        texts = [_merge_row(v[0]) for v in visual]
        if _is_label(cells, texts, table.bbox[0]):
            add(texts[:1])
            texts = texts[1:]
        add(texts)
    return placed


def _is_label(cells: list[_Cell], texts: list[Line], table_x0: float) -> bool:
    """一行的第一格是不是标签：在表格最左一列、字数少，并且要么这一行只有两格、右格更长，
    要么它竖着跨了好几行（合并格）。最左一列被上面的合并格占掉的行，剩下的第一格不算标签。"""
    if len(texts) < 2 or len(texts[0].text) > LABEL_MAX_LEN or cells[0].bbox[0] - table_x0 > EDGE_EPS * 2:
        return False
    if len(texts) == 2 and len(texts[1].text) > len(texts[0].text):
        return True
    height = [c.bbox[3] - c.bbox[1] for c in cells]
    return all(height[0] > 1.5 * h for h in height[1:])


# ───────────────────────── 表格 ─────────────────────────


def _overlap(box: Box, l: Line) -> float:
    w = min(box[2], l.x1) - max(box[0], l.x0)
    h = min(box[3], l.y1) - max(box[1], l.y0)
    return w * h if w > 0 and h > 0 else 0.0


def _take_tables(lines: list[Line], boxes: list[TableBox]) -> tuple[list[Line], list[_Table]]:
    """中心落在表格里的行，归到和它重叠最多的格子（文字超出格子时，它的大半截仍在自己的格子里）。

    有字的格子不到 TABLE_MIN_FILLED 个、或不到一半，就不算表格，行照常走分栏。
    返回（表格之外的行，有效的表格）。
    """
    tables: list[_Table] = []
    for box in boxes:
        cells = [[_Cell(c) for c in row] for row in box.rows]
        flat = [c for row in cells for c in row]
        if not flat:
            continue
        x0, y0, x1, y1 = box.bbox
        outside: list[Line] = []
        for l in lines:
            cx, cy = (l.x0 + l.x1) / 2, (l.y0 + l.y1) / 2
            best = max(flat, key=lambda c: _overlap(c.bbox, l)) if x0 <= cx <= x1 and y0 <= cy <= y1 else None
            if best is not None and _overlap(best.bbox, l) > 0:
                best.lines.append(l)
            else:
                outside.append(l)
        filled = sum(1 for c in flat if c.lines)
        if filled < TABLE_MIN_FILLED or 2 * filled < len(flat):
            continue
        lines = outside
        tables.append(_Table(box.bbox, [[c for c in row if c.lines] for row in cells if any(c.lines for c in row)]))
    return lines, tables


def _stand_in(table: _Table) -> _TableLine:
    ls = table.lines
    x0, y0, x1, y1 = table.bbox
    return _TableLine(ls[0].page_no, x0, y0, x1, y1, "".join(l.text for l in ls), _body_font_size(ls), False,
                      table=table)


# ───────────────────────── 递归切分 ─────────────────────────


def _order(lines: list[Line], region: _Region, col: int | None = None,
           depth: int = 0, allow_y_cut: bool = True) -> list[_Placed]:
    """返回 lines 的阅读顺序。col 为 None 表示还没进入任何一栏。"""
    if not lines:
        return []
    stats = region.stats
    band = _best_band(lines, region.page_width) if depth < MAX_DEPTH else None

    if band and band.clearness >= settings.LAYOUT_DOUBLE_MIN_C:
        spanning = band.blocked | _header_rows_above_right_column(lines, band, region.page_width)
        rest = [l for i, l in enumerate(lines) if i not in spanning]
        if not (region.date_columns and _is_date_column(rest, band)):   # 时间轴：不切，往下走横切 / 叶子，按行读
            _record_cut(stats, band, column_lines=len(lines) - len(spanning))
            if spanning:
                return _split_by_spanning_rows(lines, spanning, region, col, depth)
            return _split_columns(lines, band, region, col, depth)

    if allow_y_cut:
        segments = _y_segments(lines)
        if len(segments) > 1:  # 每段再试一次找空白带，但不再继续横切（已经在所有留白处切过了）
            return [p for seg in segments for p in _order(seg, region, col, depth + 1, allow_y_cut=False)]

    clearness = band.clearness if band else 0.0
    stats.leaf_clearness.append(clearness)
    if settings.LAYOUT_SINGLE_MAX_C < clearness < settings.LAYOUT_DOUBLE_MIN_C:
        stats.unknown_lines += len(lines)
    return _place_rows(lines, 0 if col is None else col, stats)


def _record_cut(stats: _PageStats, band: _Band, column_lines: int) -> None:
    stats.cut_clearness.append(band.clearness)
    if column_lines > stats.main_gap_lines:
        stats.main_gap, stats.main_gap_lines = (round(band.x0, 1), round(band.x1, 1)), column_lines


def _split_columns(lines: list[Line], band: _Band, region: _Region, col: int | None, depth: int) -> list[_Placed]:
    """X 切：先读左栏，再读右栏。已经在某一栏里的嵌套切分沿用外层的栏号。"""
    left = [l for l in lines if l.x1 <= band.x0 + EDGE_EPS]
    right = [l for l in lines if l.x0 >= band.x1 - EDGE_EPS]
    return (_order(left, region, 0 if col is None else col, depth + 1)
            + _order(right, region, 1 if col is None else col, depth + 1))


def _split_by_spanning_rows(lines: list[Line], spanning: set[int], region: _Region,
                            col: int | None, depth: int) -> list[_Placed]:
    """自上而下扫描：连续的跨栏行自成一段直接落位，夹在它们之间的普通行作为一段递归处理。"""
    placed: list[_Placed] = []
    run: list[Line] = []
    run_is_spanning = False

    def flush() -> None:
        if not run:
            return
        if run_is_spanning:
            placed.extend(_place_rows(run, -1 if col is None else col, region.stats))
        else:
            placed.extend(_order(list(run), region, col, depth + 1))
        run.clear()

    for i, l in sorted(enumerate(lines), key=lambda t: (t[1].y0, t[1].x0)):
        if (i in spanning) != run_is_spanning:
            flush()
            run_is_spanning = i in spanning
        run.append(l)
    flush()
    return placed


def _y_segments(lines: list[Line]) -> list[list[Line]]:
    """Y 切：在 ≥ 1.5 倍行高的水平留白处把区域切成上下几段。"""
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


# ───────────────────────── 页眉页脚 ─────────────────────────


def _drop_headers_footers(lines: list[Line], pages: list[PageInfo]) -> list[Line]:
    """删掉页边带内的页码，以及在多页同一位置重复出现的文字。"""
    height = {p.page_no: p.height for p in pages}
    ratio = settings.LAYOUT_HEADER_FOOTER_RATIO

    def in_margin(l: Line) -> bool:
        h = height[l.page_no]
        return l.y1 <= ratio * h or l.y0 >= (1 - ratio) * h

    def position_key(l: Line) -> tuple[str, int]:
        return l.text, round(l.y0 / 4)

    pages_seen: dict[tuple[str, int], set[int]] = {}
    for l in lines:
        if in_margin(l):
            pages_seen.setdefault(position_key(l), set()).add(l.page_no)

    def is_noise(l: Line) -> bool:
        return in_margin(l) and (bool(_PAGE_NO.match(l.text)) or len(pages_seen[position_key(l)]) >= 2)

    return [l for l in lines if not is_noise(l)]


# ───────────────────────── 行 → 块 ─────────────────────────


def _join_wrapped(prev: str, nxt: str) -> str:
    """折行拼回一句：中文之间不加空格，英文 / 数字之间补一个空格。"""
    if prev and nxt and prev[-1].isascii() and nxt[0].isascii() and prev[-1] != " ":
        return prev + " " + nxt
    return prev + nxt


def _is_heading_like(l: Line, body_size: float) -> bool:
    return l.font_size >= body_size + HEADING_EXTRA_SIZE or (l.is_bold and len(l.text) <= HEADING_MAX_LEN)


def _line_was_full(p: _Placed) -> bool:
    """这一行是否写到了栏的右边界——写满了，下一行才可能是它的折行。"""
    slack = max(WRAP_SLACK_EM * p.line.font_size, WRAP_SLACK_RATIO * (p.leaf_x1 - p.leaf_x0))
    return p.line.x1 >= p.leaf_x1 - slack


def _starts_new_block(prev: _Placed | None, cur: _Placed, body_size: float, head: _Placed | None = None) -> bool:
    """cur 是另起一块，还是上一行的折行？任何一条成立就另起一块。head 是当前块的第一行。"""
    if prev is None:
        return True
    a, b = prev.line, cur.line
    different_place = cur.leaf != prev.leaf or a.page_no != b.page_no
    different_style = a.font_size != b.font_size or a.is_bold != b.is_bold
    # 相隔较远的几段拼成的行（「标题 …… 日期」「日期 …… 标题」）是新条目的标题行，不会是上一句的折行
    explicit_start = _BULLET.match(b.text) is not None or _is_heading_like(b, body_size) or cur.tabular
    prev_is_complete = _is_heading_like(a, body_size) or prev.tabular or not _line_was_full(prev)
    paragraph_gap = b.y0 - a.y1 > PARAGRAPH_GAP * b.height
    # "标签：内容"列表的下一项：上一项恰好写满整行时，光看行宽会把它误判成折行。
    # 要求当前块也以标签开头，普通段落里碰巧以"xx："起头的折行不受影响
    next_labeled_item = (head is not None and _LABEL.match(head.line.text) is not None
                         and _LABEL.match(b.text) is not None)
    return (different_place or different_style or explicit_start or prev_is_complete or paragraph_gap
            or next_labeled_item)


def _to_blocks(placed: list[_Placed], body_size: float) -> list[Block]:
    blocks: list[Block] = []
    prev: _Placed | None = None
    head: _Placed | None = None          # 当前块的第一行
    for cur in placed:
        l = cur.line
        if _starts_new_block(prev, cur, body_size, head):
            head = cur
            blocks.append(Block(len(blocks), l.page_no, cur.col, l.x0, l.y0, l.x1, l.y1,
                                l.text, l.font_size, l.is_bold))
        else:
            b = blocks[-1]
            b.text = _join_wrapped(b.text, l.text)
            b.x0, b.y0 = min(b.x0, l.x0), min(b.y0, l.y0)
            b.x1, b.y1 = max(b.x1, l.x1), max(b.y1, l.y1)
        prev = cur
    return blocks


def assign_offsets(blocks: list[Block]) -> str:
    """拼出 full_text 并固定每块的字符偏移。全系统只有这一处定义"坐标系"。"""
    cursor = 0
    for i, b in enumerate(blocks):
        b.block_index = i
        b.char_start, b.char_end = cursor, cursor + len(b.text)
        cursor = b.char_end + 1  # 块之间以一个 "\n" 连接
    return "\n".join(b.text for b in blocks)


# ───────────────────────── 入口 ─────────────────────────


def _body_font_size(lines: list[Line]) -> float:
    """正文字号：按字符数加权的中位数。"""
    sizes = sorted(l.font_size for l in lines for _ in range(len(l.text)))
    return sizes[len(sizes) // 2] if sizes else 10.5


def _summarize_page(page: PageInfo, s: _PageStats) -> PageLayout:
    if s.total == 0:
        return PageLayout(page.page_no, "single", 1.0, None)
    if s.chars and s.table_chars / s.chars >= settings.LAYOUT_TABLE_CHAR_RATIO:
        return PageLayout(page.page_no, "table", 1.0, None)
    if s.unknown_lines / s.total >= COLUMN_PAGE_RATIO:
        return PageLayout(page.page_no, "unknown", 0.5, None)
    if s.main_gap and s.main_gap_lines / s.total >= COLUMN_PAGE_RATIO:
        center = sum(s.main_gap) / 2 / page.width
        kind = "double" if 0.4 <= center <= 0.6 else "sidebar"
        return PageLayout(page.page_no, kind, round(min(s.cut_clearness), 3), s.main_gap)
    # 单栏：最像"有空白带"的那个叶子越清晰，我们对"它是单栏"就越没把握
    doubt = max((c for c in s.leaf_clearness if c <= settings.LAYOUT_SINGLE_MAX_C), default=0.0)
    return PageLayout(page.page_no, "single", round(1 - doubt, 3), None)


def analyze_layout(extracted: ExtractResult, *, date_columns: bool = True) -> LayoutResult:
    """date_columns=False 关掉"时间轴日期列"规则，只给评测脚本做消融对照用（表格识别的消融是清空 extracted.tables）。"""
    lines = _drop_headers_footers(extracted.lines, extracted.pages)

    placed: list[_Placed] = []
    pages: list[PageLayout] = []
    leaf_seq = 0
    for page in extracted.pages:
        page_lines = [l for l in lines if l.page_no == page.page_no]
        rest, tables = _take_tables(page_lines, [t for t in extracted.tables if t.page_no == page.page_no])
        stats = _PageStats(
            total=len(page_lines),
            chars=sum(len(l.text) for l in page_lines),
            table_chars=sum(len(l.text) for t in tables for l in t.lines),
            leaf_seq=leaf_seq,  # 叶子编号跨页连续，保证全局唯一
        )
        placed.extend(_order(rest + [_stand_in(t) for t in tables], _Region(page.width, stats, date_columns)))
        leaf_seq = stats.leaf_seq
        pages.append(_summarize_page(page, stats))

    blocks = _to_blocks(placed, _body_font_size(lines))
    return LayoutResult(blocks, assign_offsets(blocks), pages)
