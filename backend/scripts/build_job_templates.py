"""把手写的岗位模板解析成要求项：python scripts/build_job_templates.py

模板原文在 data/job_templates/<方向>/*.txt（目录名是求职方向的 key，见 app/domains；第一行是岗位名称，其余是 JD），
解析复用线上的 parse_jd（按模板的方向取提示词），结果连同原文写进 data/job_templates.json 一起提交；
seed.sql 再由 dump_seed.py 从 json 生成。这样导入数据库时不调模型，每次导入的要求项都一样。
原文没改过的模板直接沿用 json 里的解析结果（只按当前词典重算 skill_id），不重新调模型：
模型结果的缓存只有 7 天，过期后重新解析可能拆得不一样，已有投递引用的要求项就对不上了。
改完记得接着跑 dump_seed.py（tests/test_seed_sync.py 会检查三者是否一致）。

需要 .env 里的 DeepSeek key，以及本机 MySQL / Redis：调用照常走缓存、限流和审计，没改过的模板直接命中缓存。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.domains import DOMAINS  # noqa: E402
from app.llm import prompts  # noqa: E402
from app.matching.skill_dict import SkillDict, SkillEntry  # noqa: E402
from app.services.job_service import normalize_jd  # noqa: E402
from scripts.dump_seed import TEMPLATES_PATH, load_skills, load_templates  # noqa: E402

SOURCE_DIR = BACKEND.parent / "data" / "job_templates"


def load_sources(directory: Path = SOURCE_DIR) -> list[dict]:
    """[{title, domain, raw_text}]，方向按 DOMAINS 的顺序、同一方向内按文件名排序。
    raw_text 与用户粘贴 JD 时一样先经过 normalize_jd。"""
    sources = []
    for domain in DOMAINS:
        for path in sorted((directory / domain).glob("*.txt")):
            title, _, body = path.read_text(encoding="utf-8").partition("\n")
            sources.append({"title": title.strip(), "domain": domain, "raw_text": normalize_jd(body)})
    return sources


def skill_dict() -> SkillDict:
    """技能词典直接从 CSV 建：和 seed.sql 同一个来源，不依赖库里导入的是不是最新的。"""
    return SkillDict(SkillEntry(s["id"], s["canonical_name"], tuple(s["aliases"])) for s in load_skills())


def main() -> None:
    from app.llm.client import get_llm_client
    from app.matching.jd_parser import parse_jd

    llm, skills = get_llm_client(), skill_dict()
    parsed = {(t["title"], t.get("domain", "cs"), t["raw_text"]): t["requirements"]
              for t in (load_templates() if TEMPLATES_PATH.exists() else [])}
    templates = []
    for src in load_sources():
        reqs = parsed.get((src["title"], src["domain"], src["raw_text"]))
        if reqs is not None:                          # 原文没变：沿用，只按当前词典重算 skill_id
            reqs = [{**r, "skill_id": skills.lookup(r["skill"]) if r["skill"] else None} for r in reqs]
            print(f"\n{src['title']}（{src['domain']}）：原文没变，沿用 {len(reqs)} 条")
        else:
            result = parse_jd(src["title"], src["raw_text"], llm, skills, domain=DOMAINS[src["domain"]])
            if result.error or not result.requirements:
                sys.exit(f"「{src['title']}」解析失败：{result.error or '没有识别出要求项'}")
            reqs = result.requirements
            print(f"\n{src['title']}（{src['domain']}）：{len(reqs)} 条" + (f"，丢弃 {result.rejected} 条" if result.rejected else ""))
        for r in reqs:
            skill = f"  [{r['skill']} → {r['skill_id']}]" if r["skill"] else ""
            print(f"  {r['id']:>2}. {r['req_type']:<4} {r['category']:<10} {r['content']}{skill}")
        templates.append({**src, "requirements": reqs})

    data = {"prompt_version": prompts.JD_VERSION, "model": settings.CHAT_MODEL, "templates": templates}
    TEMPLATES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"\n已生成 {TEMPLATES_PATH}：{len(templates)} 个模板。接着运行 python scripts/dump_seed.py")


if __name__ == "__main__":
    main()
