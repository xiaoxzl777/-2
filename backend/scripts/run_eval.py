"""诊断 / 匹配评测：python scripts/run_eval.py [--task diagnose|match] [--modes ...] [--repeat 1] [--limit N]
（先跑 scripts/gen_eval_set.py 生成评测集；需要本机 MySQL、Redis 和 .env 里的 DeepSeek key）

流程：每份 PDF 先走一遍和线上一样的解析（走缓存：解析不是被测对象）；再按"模式 × 重复次数"在评测批次号下跑诊断 / 匹配图
（绕过缓存，llm_calls 里每次调用都带 run_id，事后能查）。

--task match（8.3 (2) 匹配消融，精简版）：简历用规则类降质版（技能栏多写了一个经历里没用过的技能），每份配 8 条岗位要求，
满足与否按底稿内容就能确定（见 match_requirements）。指标：三种模式与标准答案的一致率（分要求类别）、交给模型的条数、
引用被作废的条数、花费与用时。

--task diagnose 的指标（05-evaluation-and-plan 8.1、8.3 (3)(4)）：
  检出（位置）      有任意一条问题的证据区间和缺陷所在的文字重叠
  检出（类型）      重叠的问题里有期望的那条规则 / 那一类问题
  干净底稿的问题数  三种模式各自的"噪声"：底稿刻意写得干净，但模型仍可能提出合理意见，只作参考
  拦截率            模型给出的问题里，引用在原文里找不到、被拦下的比例（溯源）
  定位准确率        语义类缺陷：模型在注入的那条描述上报出期望类型的问题时，证据确实落在注入的那句话上的比例
  花费、用时        每份简历一次诊断
原始结果（每份、每种模式、每次的全部问题）和汇总写一份 JSON 到 data/eval_runs/。
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.diagnose.types import iter_units  # noqa: E402
from app.graphs import diagnose_graph, match_graph  # noqa: E402
from app.llm.client import current_run_id, get_llm_client  # noqa: E402
from app.matching.skill_dict import SkillDict, annotate_skills  # noqa: E402
from app.parser.extract import extract_pdf  # noqa: E402
from app.parser.layout import analyze_layout  # noqa: E402
from app.parser.pii import extract_basics, mask_pii  # noqa: E402
from app.parser.section import detect_sections  # noqa: E402
from app.parser.section_llm import classify_sections  # noqa: E402
from app.parser.structure import extract_structure  # noqa: E402
from app.services.skill_service import load_skill_dict  # noqa: E402
from scripts.eval_layout import squash  # noqa: E402
from scripts.gen_eval_set import OUT_DIR, SEED, UNUSED_SKILLS, make_base  # noqa: E402

MODES = ("rule_only", "llm_only", "hybrid")
MATCH_MODES = ("dict_only", "llm_fulltext", "hybrid")
RULE_DEFECTS = ("dequant", "weak_verb", "skill_unused", "timeline_gap")
SEMANTIC_DEFECTS = ("exaggeration", "incoherent", "unclear_ownership")


def parse(path: Path, llm, skills) -> dict:
    """和 parse_service 同样的几步，只是不落库。"""
    extracted = extract_pdf(path)
    layout = analyze_layout(extracted)
    sections = detect_sections(layout)
    basics = extract_basics(layout, sections)
    sections = classify_sections(layout, sections, basics.name, llm).sections
    structured = extract_structure(layout, sections, basics, llm)
    structure = {**structured.structure, "extraction_errors": structured.errors}
    annotate_skills(structure, layout.full_text, [s.to_dict() for s in sections], skills)
    return {"full_text": layout.full_text, "structure": structure, "masked": mask_pii(layout.full_text, name=basics.name),
            "ats_signals": extracted.ats_signals, "page_count": extracted.page_count}


def locate(full_text: str, anchor: str) -> tuple[int, int] | None:
    """anchor 在 full_text 里的区间。两边都去掉空白再找（折行处的空格可能被拼掉），再映射回原文下标。"""
    keep = [i for i, ch in enumerate(full_text) if not ch.isspace()]
    target = squash(anchor)
    pos = "".join(full_text[i] for i in keep).find(target)
    return (keep[pos], keep[pos + len(target) - 1] + 1) if target and pos >= 0 else None


def overlaps(f: dict, span: tuple[int, int]) -> bool:
    return f["char_start"] is not None and f["char_start"] < span[1] and span[0] < f["char_end"]


def kind(f: dict) -> str:
    return f["rule_code"] or f["risk_type"]


def diagnose(graph, doc: dict, mode: str, run_id: str) -> dict:
    token = current_run_id.set(run_id)
    started = time.perf_counter()
    try:
        out = graph.invoke(diagnose_graph.initial_state(
            structure=doc["structure"], full_text=doc["full_text"], masked_text=doc["masked"], mode=mode,
            ats_signals=doc["ats_signals"], page_count=doc["page_count"]))
    finally:
        current_run_id.reset(token)
    return {"findings": [f.to_dict() for f in out["findings"]],
            "llm_verified": [f.to_dict() for f in out.get("llm_findings") or []],
            "llm_rejected": [f.to_dict() for f in out.get("rejected_findings") or []],
            "cost": out.get("cost") or 0.0, "seconds": time.perf_counter() - started,
            "units_skipped": out.get("units_skipped") or 0}


def score_run(gt: dict, docs: dict[str, dict], runs: dict[str, dict]) -> dict:
    """一种模式跑一遍的指标。runs: 文件名 → diagnose() 的结果。"""
    hit = defaultdict(lambda: [0, 0, 0])            # 缺陷类型 → [位置命中, 类型命中, 总数]
    located = [0, 0]                                # 定位准确率：[证据落在注入那句话上的, 期望类型且在那条描述上的]
    clean_rule, clean_llm, verified, rejected, cost, seconds = [], [], 0, 0, [], []
    for name, run in runs.items():
        doc, meta = docs[name], gt[name]
        verified += len(run["llm_verified"])
        rejected += len(run["llm_rejected"])
        cost.append(run["cost"])
        seconds.append(run["seconds"])
        if meta["variant"] == "clean":
            clean_rule.append(sum(f["source"] == "rule" for f in run["findings"]))
            clean_llm.append(sum(f["source"] == "llm" for f in run["findings"]))
        units = iter_units(doc["structure"], doc["full_text"])
        for d in meta["defects"]:
            span = locate(doc["full_text"], d["anchor"])
            h = hit[d["type"]]
            h[2] += 1
            if span is None:
                continue                            # 解析把这段文字弄丢了：算没检出
            near = [f for f in run["findings"] if overlaps(f, span)]
            h[0] += bool(near)
            h[1] += any(kind(f) == d["expect"] for f in near)
            if d["type"] in SEMANTIC_DEFECTS:
                unit = next((u for u in units if u.char_start <= span[0] < u.char_end), None)
                same = [f for f in run["llm_verified"]
                        if unit and f["unit_id"] == unit.unit_id and f["risk_type"] == d["expect"]]
                located[1] += len(same)
                located[0] += sum(overlaps(f, span) for f in same)
    return {
        "defects": {k: {"position": v[0] / v[2], "type": v[1] / v[2], "n": v[2]} for k, v in hit.items()},
        "clean_rule_findings": statistics.mean(clean_rule) if clean_rule else 0.0,
        "clean_llm_findings": statistics.mean(clean_llm) if clean_llm else 0.0,
        "llm_verified": verified, "llm_rejected": rejected,
        "intercept_rate": rejected / (verified + rejected) if verified + rejected else None,
        "locate_precision": located[0] / located[1] if located[1] else None,
        "cost_per_resume": statistics.mean(cost), "seconds_per_resume": statistics.mean(seconds),
    }


def _mean(values: list) -> str:
    values = [v for v in values if v is not None]
    if not values:
        return "—"
    if len(values) == 1:
        return f"{values[0]:.1%}"
    return f"{statistics.mean(values):.1%}±{statistics.stdev(values):.1%}"


def report(scores: dict[str, list[dict]]) -> None:
    modes = list(scores)
    head = f"{'':<20}" + "".join(f"{m:>22}" for m in modes)
    for title, defects in [("规则类缺陷", RULE_DEFECTS), ("语义类缺陷", SEMANTIC_DEFECTS)]:
        print(f"\n{title}检出率（位置 / 类型）\n{head}")
        for d in defects:
            cells = [f"{_mean([s['defects'][d]['position'] for s in scores[m]])} / "
                     f"{_mean([s['defects'][d]['type'] for s in scores[m]])}" for m in modes]
            print(f"{d:<20}" + "".join(f"{c:>22}" for c in cells))
    print(f"\n其他{head[2:]}")
    rows = [("干净底稿·规则问题数", lambda s: f"{s['clean_rule_findings']:.2f}"),
            ("干净底稿·模型问题数", lambda s: f"{s['clean_llm_findings']:.2f}"),
            ("拦截率", lambda s: "—" if s["intercept_rate"] is None else f"{s['intercept_rate']:.1%}"),
            ("定位准确率", lambda s: "—" if s["locate_precision"] is None else f"{s['locate_precision']:.1%}"),
            ("每份花费（元）", lambda s: f"{s['cost_per_resume']:.4f}"),
            ("每份用时（秒）", lambda s: f"{s['seconds_per_resume']:.1f}")]
    for label, fmt in rows:
        print(f"{label:<17}" + "".join(f"{' / '.join(fmt(s) for s in scores[m]):>22}" for m in modes))


# ───────────────────────── 匹配消融 ─────────────────────────

FRAMEWORKS = ("Spring Boot", "Django", "Flask", "Gin")
# 每个项目一条"描述里有依据、但不点名技能"的要求：词典判不了，得读懂描述
PROJECT_REQUIREMENTS = {
    "校园二手交易平台": "有支付回调或订单系统的开发经验",
    "在线考试系统": "有数据库表结构设计的经验",
    "图书馆座位预约小程序": "有预约或排队类业务的开发经验",
    "秒杀系统": "有高并发场景下的库存扣减或限流经验",
    "课程推荐系统": "有推荐算法的实现经验",
    "个人博客系统": "有持续集成（CI）流水线的搭建经验",
}
MATCH_KINDS = ("skill_used", "skill_listed", "skill_absent", "alternative", "project", "education", "years", "other")


def match_requirements(index: int, skills: SkillDict) -> list[dict]:
    """第 index 份底稿（从 0 起）的 8 条岗位要求，expect 是标准答案。

    简历是规则类降质版：技能栏多写了一个经历里没用过的技能（listed），所以"熟悉 listed"是部分满足；
    其余几处降质（删数字、弱动词、时间空窗）不影响匹配——实习合计约半年，"3 年以上"照样不满足。
    """
    base = make_base(random.Random(SEED * 100 + index), index)
    stack = [s for p in base["projects"] for s in p["stack"]]
    listed = UNUSED_SKILLS[index % len(UNUSED_SKILLS)]           # 和 gen_eval_set 加进技能栏的是同一个
    absent = UNUSED_SKILLS[(index + 1) % len(UNUSED_SKILLS)]     # 简历里完全没有
    have = next(f for f in FRAMEWORKS if f in stack)
    lack = next(f for f in FRAMEWORKS if f not in stack)
    rows = [
        ("skill_used", "skill", stack[0], f"熟悉 {stack[0]}", "hit"),
        ("skill_listed", "skill", listed, f"熟悉 {listed}", "partial"),
        ("skill_absent", "skill", absent, f"熟悉 {absent}", "miss"),
        ("alternative", "skill", None, f"用过 {lack} 或 {have} 等 Web 后端框架", "hit"),   # 二选一：JD 解析不填技能
        ("project", "experience", None, PROJECT_REQUIREMENTS[base["projects"][0]["name"]], "hit"),
        ("education", "education", None, "本科及以上学历", "hit"),
        ("years", "experience", None, "3 年以上工作经验", "miss"),
        ("other", "other", None, "英语达到 CET-6 水平", "miss"),
    ]
    return [{"id": k + 1, "kind": kind, "expect": expect, "req_type": "hard", "category": category, "skill": skill,
             "skill_id": skills.lookup(skill) if skill else None, "content": content, "quote": content, "weight": 1.0}
            for k, (kind, category, skill, content, expect) in enumerate(rows)]


def match(graph, doc: dict, requirements: list[dict], mode: str, run_id: str) -> dict:
    token = current_run_id.set(run_id)
    started = time.perf_counter()
    try:
        out = graph.invoke(match_graph.initial_state(
            requirements=[{k: v for k, v in r.items() if k not in ("kind", "expect")} for r in requirements],
            structure=doc["structure"], full_text=doc["full_text"], masked_text=doc["masked"], mode=mode))
    finally:
        current_run_id.reset(token)
    return {"items": [i.to_dict() for i in out["items"]], "cost": out.get("cost") or 0.0,
            "llm_items": out.get("llm_item_count") or 0, "hallucinations": out.get("hallucination_count") or 0,
            "seconds": time.perf_counter() - started}


def score_match_run(requirements: dict[str, list[dict]], runs: dict[str, dict]) -> dict:
    right = defaultdict(lambda: [0, 0])               # 要求类别 → [判对的, 总数]
    for name, run in runs.items():
        status = {i["requirement_id"]: i["status"] for i in run["items"]}
        for r in requirements[name]:
            right[r["kind"]][0] += status.get(r["id"]) == r["expect"]
            right[r["kind"]][1] += 1
    total = [sum(v[0] for v in right.values()), sum(v[1] for v in right.values())]
    return {"accuracy": total[0] / total[1], "kinds": {k: v[0] / v[1] for k, v in right.items()},
            "llm_items_per_resume": statistics.mean(r["llm_items"] for r in runs.values()),
            "hallucinations": sum(r["hallucinations"] for r in runs.values()),
            "cost_per_resume": statistics.mean(r["cost"] for r in runs.values()),
            "seconds_per_resume": statistics.mean(r["seconds"] for r in runs.values())}


def report_match(scores: dict[str, list[dict]]) -> None:
    modes = list(scores)
    print(f"\n一致率（判定 = 标准答案）\n{'':<16}" + "".join(f"{m:>20}" for m in modes))
    for kind in MATCH_KINDS:
        print(f"{kind:<16}" + "".join(f"{_mean([s['kinds'][kind] for s in scores[m]]):>20}" for m in modes))
    print(f"{'总体':<15}" + "".join(f"{_mean([s['accuracy'] for s in scores[m]]):>20}" for m in modes))
    rows = [("每份交给模型的条数", "llm_items_per_resume", ".1f"), ("引用被作废的条数", "hallucinations", ".1f"),
            ("每份花费（元）", "cost_per_resume", ".4f"), ("每份用时（秒）", "seconds_per_resume", ".1f")]
    for label, key, fmt in rows:                       # 多次重复时取平均
        print(f"{label:<12}" + "".join(f"{statistics.mean(s[key] for s in scores[m]):>20{fmt}}" for m in modes))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=("diagnose", "match"), default="diagnose")
    parser.add_argument("--modes", nargs="+", default=None, choices=MODES + MATCH_MODES[:2],
                        help="默认：diagnose 跑 rule_only / llm_only / hybrid，match 跑 dict_only / llm_fulltext / hybrid")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 份底稿，试跑用")
    args = parser.parse_args()
    modes = args.modes or list(MODES if args.task == "diagnose" else MATCH_MODES)

    gt = json.loads((OUT_DIR / "gt.json").read_text(encoding="utf-8"))
    if args.limit:
        gt = {k: v for k, v in gt.items() if v["base"] <= args.limit}
    if args.task == "match":
        gt = {k: v for k, v in gt.items() if v["variant"] == "rule"}
    llm = get_llm_client()
    with SessionLocal() as db:
        skills = load_skill_dict(db)

    started = time.perf_counter()
    docs = {name: parse(OUT_DIR / name, llm, skills) for name in gt}
    print(f"解析 {len(docs)} 份，用时 {time.perf_counter() - started:.0f}s")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    if args.task == "diagnose":
        graph = diagnose_graph.build_diagnose_graph(llm)
    else:
        graph = match_graph.build_match_graph(llm)
        requirements = {name: match_requirements(gt[name]["base"] - 1, skills) for name in gt}
    raw: dict[str, dict] = defaultdict(dict)
    scores: dict[str, list[dict]] = defaultdict(list)
    for mode in modes:
        for r in range(args.repeat):
            run_id = f"{'diag' if args.task == 'diagnose' else 'match'}-{stamp}-{mode}-{r + 1}"
            if args.task == "diagnose":
                runs = {name: diagnose(graph, doc, mode, run_id) for name, doc in docs.items()}
                scores[mode].append(score_run(gt, docs, runs))
            else:
                runs = {name: match(graph, doc, requirements[name], mode, run_id) for name, doc in docs.items()}
                scores[mode].append(score_match_run(requirements, runs))
            raw[mode][r + 1] = runs
            print(f"{mode} 第 {r + 1} 次完成（run_id={run_id}）")

    (report if args.task == "diagnose" else report_match)(scores)
    out = settings.DATA_DIR / "eval_runs" / f"{args.task}-{stamp}.json"
    out.write_text(json.dumps({"args": vars(args), "scores": scores, "raw": raw}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"\n结果已写入 {out}")


if __name__ == "__main__":
    main()
