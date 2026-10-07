"""生成种子数据 SQL：python scripts/dump_seed.py

输出 backend/sql/seed.sql，在 MySQL 中手动执行，可重复执行。内容有两部分：
- 技能词典：来自 data/skills_seed.csv（唯一事实来源），先清空 skills 再插入。
  词典是扁平的：只回答"这个词是不是某技能的另一种写法"。匹配时忽略大小写，
  所以只差大小写的别名无需重复列出（列了也无害）。
- 岗位模板：来自 data/job_templates.json（由 build_job_templates.py 解析手写的模板生成），按标题更新。
改了 CSV 或 json 就重新跑一次本脚本并一起提交（tests/test_seed_sync.py 会检查是否一致）。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CSV_PATH = BACKEND.parent / "data" / "skills_seed.csv"
TEMPLATES_PATH = BACKEND.parent / "data" / "job_templates.json"
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


def load_templates(path: Path = TEMPLATES_PATH) -> list[dict]:
    """[{title, domain, raw_text, requirements}]"""
    return json.loads(path.read_text(encoding="utf-8"))["templates"]


def _q(s: str) -> str:
    """MySQL 字符串字面量转义。"""
    return "'" + s.replace("\\", "\\\\").replace("'", "''") + "'"


def _skills_sql(skills: list[dict]) -> list[str]:
    lines = ["DELETE FROM skills;", "", "INSERT INTO skills (id, canonical_name, category, aliases) VALUES"]
    values = [
        f"  ({s['id']}, {_q(s['canonical_name'])}, {_q(s['category'])}, "
        f"{_q(json.dumps(s['aliases'], ensure_ascii=False))})"
        for s in skills
    ]
    lines.append(",\n".join(values) + ";")
    lines += ["", f"ALTER TABLE skills AUTO_INCREMENT = {len(skills) + 1};"]
    return lines


def _templates_sql(templates: list[dict]) -> list[str]:
    """按标题更新：有就改、没有就插，清单里去掉的软删除。
    不能先删再插：match_reports 按 job_id 引用岗位（ON DELETE CASCADE），删了会把用户在模板上的投递一起删掉。"""
    titles = ", ".join(_q(t["title"]) for t in templates)
    lines = [
        "-- 岗位模板：按标题更新，不删除重建（投递记录按 id 引用岗位，删了会连带删掉投递）",
        f"UPDATE jobs SET is_deleted = 1 WHERE is_template = 1 AND title NOT IN ({titles});",
    ]
    for t in templates:
        title, domain = _q(t["title"]), _q(t.get("domain", "cs"))
        lines += [
            "",
            f"SET @raw = {_q(t['raw_text'])};",
            f"SET @reqs = {_q(json.dumps(t['requirements'], ensure_ascii=False))};",
            f"UPDATE jobs SET domain = {domain}, raw_text = @raw, requirements = @reqs, parse_status = 'success', is_deleted = 0",
            f"  WHERE is_template = 1 AND title = {title};",
            "INSERT INTO jobs (user_id, is_template, title, domain, raw_text, requirements, parse_status)",
            f"  SELECT NULL, 1, {title}, {domain}, @raw, @reqs, 'success' FROM DUAL",
            f"  WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE is_template = 1 AND title = {title});",
        ]
    return lines


def render(skills: list[dict] | None = None, templates: list[dict] | None = None) -> str:
    skills = load_skills() if skills is None else skills
    templates = load_templates() if templates is None else templates
    lines = [
        "-- 种子数据：技能同义词词典 + 岗位模板",
        "-- 本文件由 scripts/dump_seed.py 从 data/skills_seed.csv 与 data/job_templates.json 自动生成，请勿手改。",
        "-- 在 MySQL 中执行；可重复执行（skills 表先清空再插入，岗位模板按标题更新）。需先执行 schema.sql。",
        "",
        "SET NAMES utf8mb4;  -- 不写的话 docker 首次建库导入时中文会变乱码（镜像执行 .sql 的客户端不是 utf8mb4）",
        f"USE `{DB_NAME}`;",
        "",
        *_skills_sql(skills),
        "",
        *_templates_sql(templates),
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    skills, templates = load_skills(), load_templates()
    SEED_PATH.write_text(render(skills, templates), encoding="utf-8", newline="\n")
    alias_count = sum(len(s["aliases"]) for s in skills)
    cats = sorted({s["category"] for s in skills})
    print(f"已生成 {SEED_PATH}：{len(skills)} 个技能，{alias_count} 个别名，分类 {cats}；{len(templates)} 个岗位模板")


if __name__ == "__main__":
    try:
        main()
    except ValueError as e:
        sys.exit(str(e))
