"""从 data/skills_seed.csv 生成种子数据 SQL：python scripts/dump_seed.py

输出 backend/sql/seed.sql，在 MySQL 中手动执行（可重复执行：先清空 skills 再插入）。
CSV 是技能词典的唯一事实来源；改了 CSV 就重新跑一次本脚本并一起提交
（tests/test_seed_sync.py 会检查两者是否一致）。

词典是扁平的：只回答"这个词是不是某技能的另一种写法"。匹配时忽略大小写，
所以只差大小写的别名无需重复列出（列了也无害）。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CSV_PATH = BACKEND.parent / "data" / "skills_seed.csv"
SEED_PATH = BACKEND / "sql" / "seed.sql"
DB_NAME = "resume_ai"


def load_skills(path: Path = CSV_PATH) -> list[dict]:
    """读 CSV 并校验。返回 [{id, canonical_name, category, aliases[]}]，id 按行号固定，保证 skill_id 稳定。"""
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    skills: list[dict] = []
    owner: dict[str, str] = {}  # 小写的词 -> 所属技能规范名；任何词只能属于一个技能
    errors: list[str] = []

    for i, row in enumerate(rows, start=1):
        name = (row["canonical_name"] or "").strip()
        category = (row["category"] or "").strip()
        aliases = [a.strip() for a in (row["aliases"] or "").split("|") if a.strip()]
        if not name or not category:
            errors.append(f"第 {i + 1} 行：canonical_name 与 category 不能为空")
            continue
        # 去掉与规范名或彼此只差大小写的重复别名
        seen = {name.lower()}
        uniq = []
        for a in aliases:
            if a.lower() not in seen:
                seen.add(a.lower())
                uniq.append(a)
        for word in [name, *uniq]:
            key = word.lower()
            if key in owner and owner[key] != name:
                errors.append(f"「{word}」同时属于「{owner[key]}」和「{name}」")
            owner[key] = name
        skills.append({"id": i, "canonical_name": name, "category": category, "aliases": uniq})

    if errors:
        raise ValueError("skills_seed.csv 校验失败：\n  " + "\n  ".join(errors))
    return skills


def _q(s: str) -> str:
    """MySQL 字符串字面量转义。"""
    return "'" + s.replace("\\", "\\\\").replace("'", "''") + "'"


def render(skills: list[dict] | None = None) -> str:
    skills = load_skills() if skills is None else skills
    lines = [
        "-- 种子数据：技能同义词词典",
        "-- 本文件由 scripts/dump_seed.py 从 data/skills_seed.csv 自动生成，请勿手改。",
        "-- 在 MySQL 中执行；可重复执行（会先清空 skills 表）。需先执行 schema.sql。",
        "",
        f"USE `{DB_NAME}`;",
        "",
        "DELETE FROM skills;",
        "",
        "INSERT INTO skills (id, canonical_name, category, aliases) VALUES",
    ]
    values = [
        f"  ({s['id']}, {_q(s['canonical_name'])}, {_q(s['category'])}, "
        f"{_q(json.dumps(s['aliases'], ensure_ascii=False))})"
        for s in skills
    ]
    lines.append(",\n".join(values) + ";")
    lines += ["", f"ALTER TABLE skills AUTO_INCREMENT = {len(skills) + 1};", ""]
    return "\n".join(lines)


def main() -> None:
    skills = load_skills()
    SEED_PATH.write_text(render(skills), encoding="utf-8", newline="\n")
    alias_count = sum(len(s["aliases"]) for s in skills)
    cats = sorted({s["category"] for s in skills})
    print(f"已生成 {SEED_PATH}：{len(skills)} 个技能，{alias_count} 个别名，分类 {cats}")


if __name__ == "__main__":
    try:
        main()
    except ValueError as e:
        sys.exit(str(e))
