"""章节识别：在排好序的块里找出"教育背景 / 项目经历 / 专业技能…"这些标题，把简历切成章节。

判定 = 标题词典 + 版面特征打分：
  词典命中 +3 ｜ 字号明显大于正文 +1 ｜ 加粗 +1 ｜ 独占一行且很短 +1 ｜ 上方有明显留白 +1
  得分 ≥ 3 判为标题；confidence = min(1, 得分 / 5)

词典匹配（兼容中文、英文、中英双语标题）：
  ① 归一化后整行 == 别名                              「教育背景」「EDUCATION」「一、项目经历」「■ 专业技能：」
  ② 中文部分是别名，且剩下的英文部分也是别名            「教育背景 Education」
  ③ 组合标题按 与 / 及 / 和 / & / 、 / 斜杠 拆开，每部分都是别名 → 取第一部分的类型   「专业技能与证书」

词典没命中、但像标题的行记为候选（other + needs_llm），由 section_llm 交给模型归类：
  · feature：字号明显大于正文
  · style：和词典认出的标题同字号、同粗细（标题和正文一样大、只是加粗的简历靠这条）
候选只在"第一个词典标题之后"才考虑——页顶的大号姓名属于 basics，不是章节标题。

全文没有教育章节时，开头段（第一个标题之前）末尾连续几块像教育经历的，切出来当作教育章节：
表格型简历的教育表常常没有标题，不切的话它留在 basics 里，而 basics 不发给模型。

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
    "basics": ["基本信息", "个人信息", "个人资料", "基本资料", "个人概况", "联系方式", "联系信息",
               "求职意向", "求职目标", "期望职位", "应聘岗位", "应聘职位", "意向岗位", "求职岗位", "期望岗位",
               "Personal Information", "Personal Info", "Personal Details", "Basic Information", "Contact",
               "Contact Information", "Contact Info", "Objective", "Career Objective"],
    "summary": ["个人简介", "自我评价", "个人评价", "自我介绍", "个人总结", "个人优势", "个人概述", "自我描述", "简介",
                "个人亮点", "核心优势", "职业概述", "个人陈述", "关于我", "个人特点", "综合评价", "自我总结", "个人小结",
                "Summary", "Profile", "About Me", "Personal Statement", "Professional Summary", "Self Evaluation",
                "Personal Summary", "Career Summary", "Highlights"],
    "education": ["教育背景", "教育经历", "教育", "学历", "学习经历", "教育信息",
                  "学历背景", "教育情况", "学业背景", "学术背景", "教育与培训", "学习情况", "主修课程", "相关课程", "核心课程",
                  "Education", "Educational Background", "Education Background", "Academic Background",
                  "Education and Training", "Coursework", "Relevant Coursework"],
    "work": ["工作经历", "工作经验", "实习经历", "实习经验", "工作实习经历", "实习工作经历", "工作及实习经历", "实习与工作经历",
             "职业经历", "实践经历", "社会实践", "校园经历", "校园经验", "在校经历", "校内经历", "学生工作", "社团经历", "社团活动",
             "工作履历", "实习履历", "职业履历", "工作背景", "从业经历", "实习实践", "实践经验", "社会实践经历",
             "校园活动", "课外活动", "社团与活动", "学生干部经历", "组织经历", "志愿服务", "志愿者经历", "志愿经历",
             "Work Experience", "Experience", "Professional Experience", "Employment", "Employment History",
             "Internship", "Internships", "Internship Experience", "Campus Experience", "Activities",
             "Extracurricular Activities", "Leadership", "Work History", "Relevant Experience",
             "Volunteer Experience", "Volunteering"],
    "projects": ["项目经历", "项目经验", "项目", "项目实践", "项目介绍", "个人项目", "开源项目", "科研经历", "科研项目",
                 "研究经历", "作品", "作品集",
                 "项目展示", "项目实战", "实践项目", "实习项目", "主要项目", "参与项目", "项目成果", "课程项目", "课程设计",
                 "毕业设计", "开发经历", "技术经历", "个人作品", "科研实践",
                 "Projects", "Project", "Project Experience", "Research", "Research Experience", "Portfolio",
                 "Personal Projects", "Academic Projects", "Project Highlights"],
    "skills": ["专业技能", "技能", "技术栈", "技能特长", "个人技能", "掌握技能", "技术能力", "技能清单", "专业能力",
               "IT技能", "语言能力", "技能与证书",
               "技能证书", "职业技能", "技术专长", "技术技能", "核心技能", "专业特长", "技能与特长", "计算机能力", "计算机技能",
               "Skills", "Skill", "Technical Skills", "Tech Stack", "Technologies", "Languages",
               "Core Competencies", "Technical Proficiencies", "Professional Skills"],
    "awards": ["获奖情况", "获奖经历", "荣誉奖项", "荣誉", "奖项", "所获荣誉", "荣誉证书", "证书", "资格证书", "奖励",
               "竞赛经历", "比赛经历", "获奖与证书", "奖项荣誉",
               "获奖", "所获奖项", "获奖荣誉", "荣誉奖励", "荣誉称号", "奖惩情况", "奖学金", "竞赛获奖", "竞赛奖项",
               "资质证书", "职业证书", "证书资质",
               "Awards", "Honors", "Honors and Awards", "Awards and Honors", "Certifications", "Certificates",
               "Achievements", "Competitions", "Scholarships"],
    "other": ["兴趣爱好", "爱好", "其他", "其他信息", "附加信息", "论文发表", "发表论文", "专利",
              "个人爱好", "其他经历", "补充信息", "附加说明", "科研成果",
              "Interests", "Hobbies", "Others", "Additional Information", "Publications", "Patents"],
}

_NUMBERING = re.compile(r"^(?:[一二三四五六七八九十]+[、.．]|\d{1,2}[、.．)）]|[（(][一二三四五六七八九十\d]+[)）]|part\s*\d+)", re.I)
_JOINER = re.compile(r"\s*(?:与|及|和|&|＆|、|/|／|\+|＋|\band\b)\s*", re.I)   # 组合标题的连接词
_BULLET = re.compile(r"^[•·▪■◆●○◦*➢➤►▶✓☑\-–—]")
# 像教育经历的一块：学校名或学历词。但带联系方式、住址的不算——那是 basics，切走了本地就抽不到，还会被发给模型
# （「海淀区学院路」「大学城」也会命中学校名）
_EDU_HINT = re.compile(r"[一-鿿]{2,}(?:大学|学院)|本科|硕士|博士|研究生|专科|大专|学士|university|college", re.I)
_BASICS_ONLY = re.compile(r"@|\d{3}[- ]?\d{4}[- ]?\d{4}|现居|所在地|居住地|住址|地址|籍贯")
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
    char_end: int              # 左闭右开，相对 full_text
    content_start: int         # 正文（标题之后）的起始偏移；没有正文时 == char_end
    confidence: float
    matched_by: str            # dict / feature / style / llm / implicit（没有标题块：basics、切出来的教育、整篇无标题）
    needs_llm: bool = False    # 版面像标题但词典不认识 → 交给 LLM 归类

    def to_dict(self) -> dict:
        return asdict(self)


def lookup(text: str) -> str | None:
    """标题词典匹配，返回章节类型或 None。整行认不出时，组合标题拆开、每部分都认得才算，类型取第一部分的。"""
    kind = _lookup_whole(text)
    if kind:
        return kind
    parts = [p for p in _JOINER.split(_NUMBERING.sub("", text.strip())) if _norm(p)]   # 先去编号：「一、」里的顿号不是连接词
    if len(parts) >= 2:
        kinds = [_lookup_whole(p) for p in parts]
        if all(kinds):
            return kinds[0]
    return None


def _lookup_whole(text: str) -> str | None:
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


@dataclass(slots=True)
class Heading:
    index: int          # 标题块的下标
    type: str
    confidence: float
    by: str             # dict / feature / style / llm


CANDIDATE_BY = ("feature", "style")   # 词典没认出、待模型归类的候选


def _style(b: Block) -> tuple[float, bool]:
    return round(b.font_size or 0, 1), b.is_bold


def find_headings(blocks: list[Block]) -> list[Heading]:
    """词典标题，以及词典没认出、但像标题的候选。"""
    if not blocks:
        return []
    body_size = _body_font_size(blocks)
    kinds = [lookup(b.text.strip()) if len(b.text.strip()) <= MAX_HEADING_LEN else None for b in blocks]
    # 词典标题的样式（字号、粗细）；和正文一模一样的样式说明不了什么，不用它找候选
    dict_styles = {_style(b) for b, kind in zip(blocks, kinds) if kind}
    dict_styles.discard((round(body_size, 1), False))

    headings: list[Heading] = []
    seen_dict_heading = False
    for i, (b, kind) in enumerate(zip(blocks, kinds)):
        text = b.text.strip()
        if len(text) > MAX_HEADING_LEN:
            continue
        prev = blocks[i - 1] if i else None
        score = _feature_score(b, prev, body_size)
        if kind:
            headings.append(Heading(i, kind, min(1.0, (score + 3) / 5), "dict"))
            seen_dict_heading = True
            continue
        if (not seen_dict_heading or len(text) > SHORT_LEN or _BULLET.match(text)
                or text.endswith(("：", ":"))):                       # 「核心业务开发：」是项目内的小标题
            continue
        if score >= HEADING_MIN_SCORE and body_size and b.font_size >= body_size * FONT_RATIO:
            headings.append(Heading(i, "other", min(1.0, score / 5), "feature"))
        elif _style(b) in dict_styles:
            headings.append(Heading(i, "other", min(1.0, score / 5), "style"))
    return headings


def detect_sections(layout: LayoutResult) -> list[Section]:
    return build_sections(layout.blocks, find_headings(layout.blocks))


def _looks_like_education(text: str) -> bool:
    return bool(_EDU_HINT.search(text)) and not _BASICS_ONLY.search(text)


def build_sections(blocks: list[Block], headings: list[Heading]) -> list[Section]:
    """按标题把全文切成章节：每个标题管到下一个标题之前；第一个标题之前是 basics（可能切出一段教育）。"""
    if not blocks:
        return []
    headings = sorted(headings, key=lambda h: h.index)
    sections: list[Section] = []

    def add(kind: str, title: str, start: int, end: int, confidence: float, by: str, needs_llm: bool = False) -> None:
        first, last = blocks[start], blocks[end]
        if by == "implicit":            # 没有标题块，整段都是正文
            content_start = first.char_start
        elif end > start:               # 标题块之后就是正文
            content_start = blocks[start + 1].char_start
        else:                           # 只有标题、没有正文
            content_start = last.char_end
        sections.append(Section(
            type=kind, kind=_work_kind(title) if kind == "work" else None, title=title,
            block_start=start, block_end=end, char_start=first.char_start, char_end=last.char_end,
            content_start=content_start, confidence=round(confidence, 2), matched_by=by, needs_llm=needs_llm,
        ))

    if not headings:
        add("other", "", 0, len(blocks) - 1, 0.0, "implicit")
        return sections

    first = headings[0].index
    if first > 0:  # 第一个标题之前的内容：姓名、联系方式，也许还有一段没有标题的教育
        edu_start = first
        if not any(h.type == "education" for h in headings):
            while edu_start > 0 and _looks_like_education(blocks[edu_start - 1].text):
                edu_start -= 1
        if edu_start > 0:
            add("basics", "", 0, edu_start - 1, 0.6, "implicit")
        if edu_start < first:
            add("education", "", edu_start, first - 1, 0.5, "implicit")
    for n, h in enumerate(headings):
        end = headings[n + 1].index - 1 if n + 1 < len(headings) else len(blocks) - 1
        add(h.type, blocks[h.index].text.strip(), h.index, end, h.confidence, h.by, needs_llm=h.by in CANDIDATE_BY)
    return sections
