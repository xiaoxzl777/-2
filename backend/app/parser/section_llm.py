"""章节兜底：标题词典没认出的候选标题，一次交给模型归类。

候选由 section.find_headings 标出（needs_llm）：字号明显更大的短行（feature），或和词典标题同样式的短行（style）。
模型给每个候选选一类，或者说"不是标题"（项目名、公司名这类）——不是标题的并回上一节。
发给模型的是候选标题 + 下面内容的开头，先做长度不变的 PII 掩码；候选都在第一个词典标题之后，碰不到 basics。
模型的回答只认编号和类别：编号不是候选的、类别不在清单里的，按"模型没回答"处理。
模型没回答或调用失败，就和不调模型时一样：字号更大的候选仍记为 other，同样式的候选并回上一节。

领域层：不碰数据库；模型调用经注入的 LLMClient。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.llm import prompts
from app.llm.client import LLMClient, LLMError, invoke_json
from app.parser.layout import LayoutResult
from app.parser.pii import mask_pii
from app.parser.section import Heading, Section, build_sections

logger = logging.getLogger("app.parse")

PREVIEW_CHARS = 80   # 每个候选附上它下面内容的前这么多字
TYPES = {"education", "work", "projects", "skills", "awards", "summary", "other", "none"}


class _Item(BaseModel):
    id: int
    type: str


class _SectionsOut(BaseModel):
    items: list[_Item] = Field(default_factory=list)


@dataclass(slots=True)
class ClassifyResult:
    sections: list[Section]
    cost: float = 0.0
    error: str | None = None


def classify_sections(layout: LayoutResult, sections: list[Section], name: str | None, llm: LLMClient,
                      *, ref: tuple[str, int] | None = None) -> ClassifyResult:
    candidates = [s for s in sections if s.needs_llm]
    if not candidates:
        return ClassifyResult(sections)

    masked = mask_pii(layout.full_text, name=name)
    rows = []
    for n, s in enumerate(candidates, 1):
        title = masked[s.char_start: layout.blocks[s.block_start].char_end]
        preview = masked[s.content_start: min(s.char_end, s.content_start + PREVIEW_CHARS)].replace("\n", " / ")
        rows.append(f"[#{n}] {title}\n    下面的内容：{preview or '（没有内容）'}")
    known = "、".join(s.title for s in sections if s.matched_by == "dict") or "（没有）"
    messages = [("system", prompts.SECTION_SYSTEM),
                ("user", prompts.SECTION_USER.format(known=known, candidates="\n".join(rows)))]

    try:
        parsed, cost, error = invoke_json(llm, "section", messages, schema=_SectionsOut,
                                          prompt_version=prompts.SECTION_VERSION, ref=ref)
    except LLMError as e:
        parsed, cost, error = None, 0.0, str(e)
    if error:
        error = f"section: {error}"
        logger.warning("章节归类失败 %s", error)

    decided: dict[int, str] = {}   # 候选标题块的下标 → 模型给的类别
    for item in parsed.items if parsed else []:
        if 1 <= item.id <= len(candidates) and item.type in TYPES:
            decided[candidates[item.id - 1].block_start] = item.type

    headings: list[Heading] = []
    for s in sections:
        if s.matched_by == "implicit":
            continue                      # basics、切出来的教育由 build_sections 重新推出
        kind = decided.get(s.block_start) if s.needs_llm else None
        if kind == "none":
            continue                      # 不是标题：并回上一节
        if kind:
            headings.append(Heading(s.block_start, kind, s.confidence, "llm"))
        elif s.matched_by != "style":     # 没有定论：字号更大的仍记为 other，同样式的并回上一节
            headings.append(Heading(s.block_start, s.type, s.confidence, s.matched_by))
    return ClassifyResult(build_sections(layout.blocks, headings), cost, error)
