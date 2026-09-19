"""章节识别：在排好序的块里找出"教育背景 / 项目经历 / 专业技能…"这些标题，把简历切成章节。

判定 = 标题词典 + 版面特征打分：
  词典命中 +3 ｜ 字号明显大于正文 +1 ｜ 加粗 +1 ｜ 独占一行且很短 +1 ｜ 上方有明显留白 +1
  得分 ≥ 3 判为标题；confidence = min(1, 得分 / 5)

词典匹配分三步（兼容中文、英文、中英双语标题）：
  ① 归一化后整行 == 别名                              「教育背景」「EDUCATION」「一、项目经历」「■ 专业技能：」
  ② 中文部分是别名，且剩下的英文部分也是别名            「教育背景 Education」
  ③ 只含英文时同 ①（别名表内已含英文写法）

词典没命中、但版面上很像标题的行（字号更大 + 其他特征）记为 other 并标 needs_llm，留给 LLM 归类兜底。
这类候选只在"第一个词典标题之后"才考虑——页顶的大号姓名属于 basics，不是章节标题。

领域层：纯函数，不碰数据库，不调任何 API。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.parser.layout import Block, LayoutResult

HEADING_MIN_SCORE = 3
FONT_RATIO = 1.1            # 标题字号 ≥ 正文 × 1.1（实测常见组合：正文 10.5 / 标题 12）
SHORT_LEN = 12              # "很短"的上限
MAX_HEADING_LEN = 30        # 超过这个长度的块不可能是章节标题
GAP_FACTOR = 0.6            # 上方留白 ≥ 0.6 倍行高（正常行间留白约 0.1–0.3 倍）

# 章节类型 → 别名（写法随意，加载时统一归一化）
_ALIASES: dict[str, list[str]] = {
    "basics": ["基本信息", "个人信息", "个人资料", "联系方式", "求职意向", "求职目标", "期望职位", "应聘岗位",
               "Personal Information", "Personal Info", "Basic Information", "Contact", "Contact Information",
               "Objective", "Career Objective"],
    "summary": ["个人简介", "自我评价", "个人评价", "自我介绍", "个人总结", "个人优势", "个人概述", "自我描述", "简介",
                "Summary", "Profile", "About Me", "Personal Statement", "Professional Summary", "Self Evaluation"],
    "education": ["教育背景", "教育经历", "教育", "学历", "学习经历", "教育信息",
                  "Education", "Educational Background", "Education Background", "Academic Background"],
    "work": ["工作经历", "工作经验", "实习经历", "实习经验", "工作实习经历", "实习工作经历", "工作及实习经历", "实习与工作经历",
             "职业经历", "实践经历", "社会实践", "校园经历", "校园经验", "在校经历", "校内经历", "学生工作", "社团经历", "社团活动",
             "Work Experience", "Experience", "Professional Experience", "Employment", "Employment History",
             "Internship", "Internships", "Internship Experience", "Campus Experience", "Activities",
             "Extracurricular Activities", "Leadership"],
    "projects": ["项目经历", "项目经验", "项目", "项目实践", "项目介绍", "个人项目", "开源项目", "科研经历", "科研项目",
                 "研究经历", "作品", "作品集",
                 "Projects", "Project", "Project Experience", "Research", "Research Experience", "Portfolio"],
    "skills": ["专业技能", "技能", "技术栈", "技能特长", "个人技能", "掌握技能", "技术能力", "技能清单", "专业能力",
               "IT技能", "语言能力", "技能与证书",
               "Skills", "Skill", "Technical Skills", "Tech Stack", "Technologies", "Languages"],
    "awards": ["获奖情况", "获奖经历", "荣誉奖项", "荣誉", "奖项", "所获荣誉", "荣誉证书", "证书", "资格证书", "奖励",
               "竞赛经历", "比赛经历", "获奖与证书", "奖项荣誉",
               "Awards", "Honors", "Honors and Awards", "Awards and Honors", "Certifications", "Certificates",
               "Achievements", "Competitions"],
    "other": ["兴趣爱好", "爱好", "其他", "其他信息", "附加信息", "论文发表", "发表论文", "专利",
              "Interests", "Hobbies", "Others", "Additional Information", "Publications", "Patents"],
}

_NUMBERING = re.compile(r"^(?:[一二三四五六七八九十]+[、.．]|\d{1,2}[、.．)）]|[（(][一二三四五六七八九十\d]+[)）]|part\s*\d+)", re.I)
_KEEP = re.compile(r"[^0-9a-z一-鿿]")
_CJK = re.compile(r"[一-鿿]")
_LATIN = re.compile(r"[a-z]")


def _norm(s: str) -> str:
    """只用于匹配，不改动任何存储的文本。去编号前缀、去装饰符号与空白、转小写。"""
    s = _NUMBERING.sub("", s.strip().lower())
    return _KEEP.sub("", s)


_LOOKUP: dict[str, str] = {_norm(alias): kind for kind, aliases in _ALIASES.items() for alias in aliases}


@dataclass(slots=True)
class Section:
    type: str                  # basics / summary / education / work / projects / skills / awards / other
    kind: str | None           # 仅 work：work / internship / campus
    title: str                 # 标题原文；basics 兜底段为 ""
    block_start: int           # 含标题块
    block_end: int             # 闭区间
    char_start: int
    char_end: int              # 开区间，相对 full_text
    content_start: int         # 正文（标题之后）的起始偏移；没有正文时 == char_end
    confidence: float
    matched_by: str            # dict / feature / implicit
    needs_llm: bool = False    # 版面像标题但词典不认识 → 交给 LLM 归类

    def to_dict(self) -> dict:
        return asdict(self)


def lookup(text: str) -> str | None:
    """标题词典三步匹配，返回章节类型或 None。"""
    n = _norm(text)
    if not n:
        return None
    if n in _LOOKUP:
        return _LOOKUP[n]
    zh = "".join(_CJK.findall(n))
    la = "".join(_LATIN.findall(n))
    # 中文 + 英文必须恰好拼出整行：有剩余（如数字）说明它不是一个纯粹的标题
    if zh and la and len(zh) + len(la) == len(n) and zh in _LOOKUP and la in _LOOKUP:
        return _LOOKUP[zh]  # 双语标题以中文部分为准
    return None


def _work_kind(title: str) -> str:
    t = title.lower()
    if "实习" in t or "intern" in t:
        return "internship"
    if any(w in t for w in ("校园", "在校", "校内", "学生", "社团", "实践", "campus", "activit", "leadership")):
        return "campus"
    return "work"


def _body_font_size(blocks: list[Block]) -> float:
    sizes = sorted(b.font_size for b in blocks if b.font_size for _ in range(len(b.text)))
    return sizes[len(sizes) // 2] if sizes else 0.0


def _feature_score(b: Block, prev: Block | None, body_size: float) -> int:
    score = 0
    if body_size and b.font_size and b.font_size >= body_size * FONT_RATIO:
        score += 1
    if b.is_bold:
        score += 1
    has_bbox = b.y0 is not None and b.y1 is not None
    single_line = not has_bbox or not b.font_size or (b.y1 - b.y0) <= 1.8 * b.font_size
    if single_line and len(b.text.strip()) <= SHORT_LEN:
        score += 1
    if prev is None or prev.page_no != b.page_no or prev.column_index != b.column_index:
        score += 1  # 页 / 栏的第一块，上方天然是留白
    elif has_bbox and prev.y1 is not None and b.y0 - prev.y1 >= GAP_FACTOR * min(b.y1 - b.y0, 1.8 * b.font_size):
        score += 1
    return score


def detect_sections(layout: LayoutResult) -> list[Section]:
    blocks = layout.blocks
    if not blocks:
        return []
    body_size = _body_font_size(blocks)

    # (块下标, 类型, 得分, 来源)
    headings: list[tuple[int, str, int, str]] = []
    seen_dict_heading = False
    for i, b in enumerate(blocks):
        text = b.text.strip()
        if len(text) > MAX_HEADING_LEN:
            continue
        prev = blocks[i - 1] if i else None
        score = _feature_score(b, prev, body_size)
        kind = lookup(text)
        if kind:
            headings.append((i, kind, score + 3, "dict"))
            seen_dict_heading = True
        elif (
            seen_dict_heading
            and score >= HEADING_MIN_SCORE
            and body_size and b.font_size >= body_size * FONT_RATIO   # 必须字号更大：只加粗的短行多是小节标题
            and len(text) <= SHORT_LEN
            and not text.endswith(("：", ":"))                         # 「核心业务开发：」是项目内的小标题
        ):
            headings.append((i, "other", score, "feature"))

    sections: list[Section] = []

    def add(kind: str, title: str, start: int, end: int, confidence: float, by: str, needs_llm: bool = False) -> None:
        first, last = blocks[start], blocks[end]
        has_title = by != "implicit"
        content_start = blocks[start + 1].char_start if has_title and end > start else (
            last.char_end if has_title else first.char_start)
        sections.append(Section(
            type=kind, kind=_work_kind(title) if kind == "work" else None, title=title,
            block_start=start, block_end=end, char_start=first.char_start, char_end=last.char_end,
            content_start=content_start, confidence=round(confidence, 2), matched_by=by, needs_llm=needs_llm,
        ))

    if not headings:
        add("other", "", 0, len(blocks) - 1, 0.0, "implicit")
        return sections

    if headings[0][0] > 0:  # 第一个标题之前的内容：姓名、联系方式
        add("basics", "", 0, headings[0][0] - 1, 0.6, "implicit")
    for n, (i, kind, score, by) in enumerate(headings):
        end = headings[n + 1][0] - 1 if n + 1 < len(headings) else len(blocks) - 1
        add(kind, blocks[i].text.strip(), i, end, min(1.0, score / 5), by, needs_llm=(by == "feature"))
    return sections
