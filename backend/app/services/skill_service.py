"""从 skills 表加载技能词典。词典只有一两百行，每次用到时现读现编译即可，不做进程内缓存——
这样在 MySQL 里重新执行 seed.sql 之后立即生效，不需要重启服务。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.matching.skill_dict import SkillDict, SkillEntry
from app.models import Skill


def load_skill_dict(db: Session) -> SkillDict:
    rows = db.scalars(select(Skill).order_by(Skill.id)).all()
    return SkillDict(SkillEntry(r.id, r.canonical_name, tuple(r.aliases or ())) for r in rows)
