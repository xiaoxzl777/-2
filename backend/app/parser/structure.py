"""结构化抽取：把每个章节拆成条目（教育 / 经历 / 项目 / 技能 / 奖项）。

核心设计——**模型只回块编号，不回文字**：
  发给模型的每个块前面带编号 [#n]；模型输出"这个条目由第 12、13 块组成"。
  条目的字符区间由这些块的偏移推出，highlight 的文字由服务端从 full_text 切片得到，
  因此每条 highlight 都与原文逐字一致（模型转述时会悄悄改标点、合并换行，直接用它的文字会定位不回去）。

其余原则：
- basics 章节不发给模型（本地正则抽取），其余文本发出前先做长度不变的 PII 掩码。
- 日期不让模型抽：用 normalize.find_date_range 在条目的块里本地识别。
- 模型给出的编号一律校验：不在本章节范围内的丢弃，全部无效的条目丢弃。

领域层：不碰数据库；模型调用经注入的 LLMClient。
"""
from __future__ import annotations

import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.diagnose.evidence import locate_span
from app.llm import prompts
from app.llm.client import LLMClient
from app.parser.layout import Block, LayoutResult
from app.parser.normalize import find_date_range
from app.parser.pii import Basics, mask_pii
from app.parser.section import Section

logger = logging.getLogger("app.parse")

MAX_PARALLEL_SECTIONS = 4


# ───────────────────────── 模型输出的形状 ─────────────────────────


class _EduEntry(BaseModel):
    school: str | None = None
    major: str | None = None
    degree: str | None = None
    block_ids: list[int] = Field(default_factory=list)


class _EducationOut(BaseModel):
    entries: list[_EduEntry] = Field(default_factory=list)


class _Highlight(BaseModel):
    block_ids: list[int] = Field(default_factory=list)


class _ExpEntry(BaseModel):
    name: str | None = None
    role: str | None = None
    tech_stack: list[str] = Field(default_factory=list)
    block_ids: list[int] = Field(default_factory=list)
    highlights: list[_Highlight] = Field(default_factory=list)


class _ExperienceOut(BaseModel):
    entries: list[_ExpEntry] = Field(default_factory=list)


class _SkillItem(BaseModel):
    name: str
    level: str | None = None
    block_id: int


class _SkillsOut(BaseModel):
    items: list[_SkillItem] = Field(default_factory=list)


class _AwardEntry(BaseModel):
    name: str | None = None
    block_ids: list[int] = Field(default_factory=list)


class _AwardsOut(BaseModel):
    entries: list[_AwardEntry] = Field(default_factory=list)


@dataclass(slots=True)
class _Spec:
    """一种章节怎么问模型：用哪个 prompt、期望什么形状的输出。章节类型同时也是 structure 里的键。"""

    schema: type[BaseModel]
    template: str
    fmt: dict = field(default_factory=dict)


_SPECS: dict[str, _Spec] = {
    "education": _Spec(_EducationOut, prompts.STRUCTURE_EDUCATION),
    "work": _Spec(_ExperienceOut, prompts.STRUCTURE_EXPERIENCE,
                  {"entry_noun": "工作 / 实习 / 校园经历", "name_desc": "公司或组织名称"}),
    "projects": _Spec(_ExperienceOut, prompts.STRUCTURE_EXPERIENCE,
                      {"entry_noun": "项目经历", "name_desc": "项目名称"}),
    "skills": _Spec(_SkillsOut, prompts.STRUCTURE_SKILLS),
    "awards": _Spec(_AwardsOut, prompts.STRUCTURE_AWARDS),
}


@dataclass(slots=True)
class StructureResult:
    structure: dict
    cost: float = 0.0
    errors: list[str] = field(default_factory=list)   # 抽取失败的章节，如 "projects: 不是合法的 JSON"


# ───────────────────────── 块编号 → 字符区间 ─────────────────────────


class _SectionBlocks:
    """一个章节的正文块（不含标题块），负责把模型给的编号变成可信的区间。"""

    def __init__(self, section: Section, blocks: list[Block], full_text: str):
        has_title = section.matched_by != "implicit"
        first = section.block_start + (1 if has_title else 0)
        self.blocks = {b.block_index: b for b in blocks[first: section.block_end + 1]}
        self.full_text = full_text

    def valid(self, ids: list[int]) -> list[int]:
        return sorted({i for i in ids if i in self.blocks})

    def span(self, ids: list[int]) -> dict | None:
        """编号 → {block_ids, char_start, char_end}。取首尾之间的连续区间，保证它是 full_text 的一段。"""
        ids = self.valid(ids)
        if not ids:
            return None
        ids = list(range(ids[0], ids[-1] + 1))
        return {"block_ids": ids,
                "char_start": self.blocks[ids[0]].char_start, "char_end": self.blocks[ids[-1]].char_end}

    def text(self, span: dict) -> str:
        return self.full_text[span["char_start"]: span["char_end"]]

    def dates(self, ids: list[int]) -> dict:
        """在条目的块里按顺序找第一个起止时间（标题行通常在最前）。"""
        for i in ids:
            found = find_date_range(self.blocks[i].text)
            if found:
                return {"start": found.start, "end": found.end, "is_present": found.is_present}
        return {"start": None, "end": None, "is_present": False}


# ───────────────────────── 各类章节的组装 ─────────────────────────


def _build_education(out: _EducationOut, sb: _SectionBlocks, _: Section) -> list[dict]:
    items = []
    for e in out.entries:
        if span := sb.span(e.block_ids):
            items.append({"school": e.school, "major": e.major, "degree": e.degree,
                          **sb.dates(span["block_ids"]), **span})
    return items


def _build_experience(out: _ExperienceOut, sb: _SectionBlocks, section: Section) -> list[dict]:
    items = []
    for e in out.entries:
        span = sb.span(e.block_ids)
        if not span:
            continue
        highlights = []
        for h in e.highlights:
            if h_span := sb.span(h.block_ids):
                highlights.append({"text": sb.text(h_span), **h_span})   # 文字来自原文切片，不来自模型
        item = {"name": e.name, "role": e.role,
                "tech_stack": [{"name": t.strip(), "skill_id": None} for t in e.tech_stack if t.strip()],
                **sb.dates(span["block_ids"]), **span, "highlights": highlights}
        if section.type == "work":
            item["kind"] = section.kind or "work"
        items.append(item)
    return items


def _build_skills(out: _SkillsOut, sb: _SectionBlocks, _: Section) -> list[dict]:
    items, seen = [], set()
    for s in out.items:
        block = sb.blocks.get(s.block_id)
        name = s.name.strip()
        if block is None or not name or name.lower() in seen:
            continue
        # 技能名必须真的出现在它声称的那个块里，否则就是模型编的
        where = locate_span(name, sb.full_text, hint=(block.char_start, block.char_end))
        if where is None or not (block.char_start <= where.start < block.char_end):
            continue
        seen.add(name.lower())
        items.append({"name": name, "level": s.level, "skill_id": None,
                      "block_ids": [block.block_index], "char_start": where.start, "char_end": where.end})
    return items


def _build_awards(out: _AwardsOut, sb: _SectionBlocks, _: Section) -> list[dict]:
    return [{"name": e.name, **sb.dates(span["block_ids"]), **span}
            for e in out.entries if (span := sb.span(e.block_ids))]


_BUILDERS = {"education": _build_education, "work": _build_experience, "projects": _build_experience,
             "skills": _build_skills, "awards": _build_awards}


# ───────────────────────── 调模型 ─────────────────────────


def _numbered_text(sb: _SectionBlocks, masked_text: str) -> str:
    return "\n".join(f"[#{i}] {masked_text[b.char_start: b.char_end]}" for i, b in sorted(sb.blocks.items()))


def _extract_section(section: Section, sb: _SectionBlocks, masked_text: str,
                     llm: LLMClient, ref: tuple[str, int] | None) -> tuple[list[dict], float, str | None]:
    """返回 (条目, 成本, 错误)。输出不合格时带着原因重试一次。"""
    spec = _SPECS[section.type]
    system = spec.template.format(title=section.title or section.type, **spec.fmt)
    messages = [("system", system), ("user", _numbered_text(sb, masked_text))]
    cost = 0.0
    for attempt in range(2):
        result = llm.invoke("structure", messages, prompt_version=prompts.STRUCTURE_VERSION,
                            schema=spec.schema, ref=ref)
        cost += result.cost
        if result.parsed is not None:
            return _BUILDERS[section.type](result.parsed, sb, section), cost, None
        if attempt == 0:
            messages = [*messages, ("assistant", result.text[:2000]),
                        ("user", prompts.STRUCTURE_RETRY.format(error=result.parse_error))]
    return [], cost, f"{section.type}: {result.parse_error}"


def _summary(section: Section, sb: _SectionBlocks) -> dict | None:
    span = sb.span(list(sb.blocks))
    return {"text": sb.text(span), **span} if span else None


def extract_structure(layout: LayoutResult, sections: list[Section], basics: Basics,
                      llm: LLMClient, *, ref: tuple[str, int] | None = None) -> StructureResult:
    structure: dict = {"basics": basics.to_dict(), "summary": None, "education": [], "work": [],
                       "projects": [], "skills": [], "awards": [], "skill_mentions": []}
    masked_text = mask_pii(layout.full_text, name=basics.name)

    jobs: list[tuple[Section, _SectionBlocks]] = []
    for section in sections:
        sb = _SectionBlocks(section, layout.blocks, layout.full_text)
        if not sb.blocks:
            continue
        if section.type == "summary" and structure["summary"] is None:
            structure["summary"] = _summary(section, sb)      # 自我评价整段就是内容，不需要模型
        elif section.type in _SPECS:
            jobs.append((section, sb))

    result = StructureResult(structure)
    if not jobs:
        return result

    def run(job: tuple[Section, _SectionBlocks]):
        return _extract_section(job[0], job[1], masked_text, llm, ref)

    # 各章节互不依赖，并行调用；copy_context 让评测批次号（ContextVar）在线程里依然可见
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_SECTIONS) as pool:
        futures = [pool.submit(contextvars.copy_context().run, run, job) for job in jobs]
        for (section, _), future in zip(jobs, futures):
            items, cost, error = future.result()
            structure[section.type].extend(items)   # 同类型的多个章节（工作经历 + 实习经历）合并
            result.cost += cost
            if error:
                result.errors.append(error)
                logger.warning("结构化抽取失败 %s", error)
    return result
