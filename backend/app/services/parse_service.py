"""解析任务：在后台把一份已上传的简历解析出来并落库。

领域层（app/parser）只做计算；这里负责读文件、改状态、写数据库。
解析产出的 full_text 与各块偏移一经落库即不再改变（系统不变量①）。
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import settings
from app.llm.client import LLMClient, LLMError
from app.matching.skill_dict import annotate_skills
from app.models import ParsedBlock, Resume
from app.parser.extract import EncryptedPdfError, ScannedPdfError, extract_pdf
from app.parser.layout import LayoutResult, analyze_layout
from app.parser.pii import extract_basics
from app.parser.section import Section, detect_sections
from app.parser.structure import extract_structure
from app.services.skill_service import load_skill_dict

logger = logging.getLogger("app.parse")

SessionFactory = Callable[[], Session]


def parse_resume(resume_id: int, session_factory: SessionFactory, llm: LLMClient) -> None:
    """BackgroundTasks 入口。自己开会话：请求的会话在响应返回后就关闭了。"""
    with session_factory() as db:
        resume = db.get(Resume, resume_id)
        if resume is None:
            return
        resume.parse_status, resume.parse_error = "parsing", None
        db.commit()

        try:
            extracted = extract_pdf(settings.DATA_DIR / resume.file_path)
            layout = analyze_layout(extracted)
            sections = detect_sections(layout)
            basics = extract_basics(layout, sections)
            structured = extract_structure(layout, sections, basics, llm, ref=("resume", resume.id))
        except ScannedPdfError:
            _mark_failed(db, resume, "scanned_pdf")
        except EncryptedPdfError:
            _mark_failed(db, resume, "encrypted_pdf")
        except LLMError:
            logger.exception("结构化抽取调用模型失败 resume_id=%s", resume_id)
            _mark_failed(db, resume, "llm_failed")
        except Exception as e:  # noqa: BLE001 —— 后台任务不能把异常抛丢，必须落成失败状态
            logger.exception("解析失败 resume_id=%s", resume_id)
            _mark_failed(db, resume, f"exception:{type(e).__name__}")
        else:
            # 个别章节抽取失败不算整体失败：其余章节照常可用，失败原因留在 structure 里供排查
            structure = {**structured.structure, "extraction_errors": structured.errors}
            section_dicts = [s.to_dict() for s in sections]
            annotate_skills(structure, layout.full_text, section_dicts, load_skill_dict(db))
            _save_result(db, resume, layout, sections, structure, extracted.page_count, extracted.ats_signals)


def _mark_failed(db: Session, resume: Resume, reason: str) -> None:
    resume.parse_status, resume.parse_error = "failed", reason[:100]
    db.commit()


def _save_result(db: Session, resume: Resume, layout: LayoutResult, sections: list[Section],
                 structure: dict, page_count: int, ats_signals: dict) -> None:
    # 重新解析（如上次被中断）时先清掉旧块，整个替换在同一事务内完成
    db.execute(delete(ParsedBlock).where(ParsedBlock.resume_id == resume.id))
    db.add_all(
        ParsedBlock(
            resume_id=resume.id, block_index=b.block_index, page_no=b.page_no, column_index=b.column_index,
            x0=b.x0, y0=b.y0, x1=b.x1, y1=b.y1, text=b.text, font_size=b.font_size, is_bold=b.is_bold,
            char_start=b.char_start, char_end=b.char_end,
        )
        for b in layout.blocks
    )
    resume.full_text = layout.full_text
    resume.sections = [s.to_dict() for s in sections]
    resume.structure = structure
    resume.layout_type = layout.layout_type
    resume.layout_confidence = layout.layout_confidence
    resume.layout_detail = [
        {"page_no": p.page_no, "layout_type": p.layout_type, "confidence": p.confidence,
         "gap": list(p.gap) if p.gap else None}
        for p in layout.pages
    ]
    resume.page_count = page_count
    resume.ats_signals = ats_signals
    resume.parse_status, resume.parse_error = "success", None
    db.commit()
