"""生成诊断评测集（程序化降质）：python scripts/gen_eval_set.py

20 份虚构的"干净"底稿，每份出 3 个版本，共 60 份单页 PDF，写进 data/eval_set/（不进仓库，随时可以重新生成）：
  clean     干净底稿
  rule      规则类降质 4 处：删量化数字 / 「协助」弱动词 / 技能栏多写一个经历里没用过的技能 / 两段实习之间造 7 个月空窗
  semantic  语义类注入 3 处（接在某条描述后面）：夸大 / 前后矛盾 / 职责不清——只有模型通道能检出
同一份里的几处缺陷落在不同的描述上，互不干扰。标准答案在 gt.json：
  {文件名: {"base": 底稿号, "variant": 版本, "defects": [{"type": 缺陷, "expect": 期望报出的规则或问题类型, "anchor": 原文里能定位到它的那段文字}]}}

底稿刻意"干净"，这样某处缺陷有没有被检出，可以干净地判断：
  · 技能栏只列项目技术栈里的技能（都在经历里出现过）；
  · 两段实习前后衔接（间隔 1 个月）；
  · 每条描述都以实打实的动词开头、带数字和结果词。
版式统一用单栏（版面不是这里的被测对象）。评测见 scripts/run_eval.py。
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from scripts.eval_layout import squash  # noqa: E402
from scripts.gen_layout_set import (CITIES, COMPANIES, GIVEN, SCHOOLS, SURNAMES, Content, Entry, H,  # noqa: E402
                                    draw_single, make_style)

SEED = 4242
N_BASES = 20
OUT_DIR = settings.DATA_DIR / "eval_set"

# ───────────────────────── 底稿内容（全部虚构） ─────────────────────────
# 每条描述：(原句, 删掉数字后的说法)。去量化后的说法保留结果词（降低 / 缩短 / 提升…），规则应报「成果缺少量化数据」

INTERNSHIPS = {
    "后端开发实习生": [
        ("负责订单服务退款流程的改造，退款处理时长从 2 天缩短到 4 小时", "负责订单服务退款流程的改造，退款处理时长明显缩短"),
        ("优化商品详情接口，加入缓存后平均响应时间从 120ms 降低到 35ms", "优化商品详情接口，加入缓存后平均响应时间明显降低"),
        ("排查线上慢查询 12 条，最慢的查询从 2s 降低到 200ms", "排查了若干线上慢查询，最慢的查询耗时明显降低"),
    ],
    "测试开发实习生": [
        ("搭建接口自动化测试流程，版本回归时间从 2 天缩短到半天", "搭建接口自动化测试流程，版本回归时间大幅缩短"),
        ("编写接口测试用例 150 余条，核心接口覆盖率提升到 90%", "编写了一批接口测试用例，核心接口覆盖率有所提升"),
        ("设计压测方案，定位出 3 个性能瓶颈，下单接口吞吐量提升 40%", "设计压测方案，定位出若干性能瓶颈，下单接口吞吐量明显提升"),
    ],
    "数据开发实习生": [
        ("开发每日用户留存报表任务，人工整理时间减少 2 小时", "开发每日用户留存报表任务，减少了人工整理时间"),
        ("重构订单数据清洗脚本，处理 30 万条数据的耗时从 40 分钟缩短到 6 分钟", "重构订单数据清洗脚本，数据处理耗时明显缩短"),
        ("搭建埋点数据校验流程，异常数据比例从 5% 降低到 0.5%", "搭建埋点数据校验流程，异常数据比例明显降低"),
    ],
    "前端开发实习生": [
        ("开发运营后台 6 个页面，运营配置一次活动的时间缩短 60%", "开发运营后台的多个页面，运营配置活动的时间明显缩短"),
        ("优化首页资源加载，首屏时间从 3.2s 降低到 1.6s", "优化首页资源加载，首屏时间明显降低"),
        ("封装通用表单组件，被 4 个项目复用，重复代码减少 30%", "封装通用表单组件，被多个项目复用，重复代码有所减少"),
    ],
}

# (项目名, 技术栈, 描述)。技术栈既写进项目条目，也是技能栏的全部来源
PROJECTS = [
    ("校园二手交易平台", ["Spring Boot", "MySQL", "Redis"], [
        ("实现订单与支付回调模块，重复回调导致的错单从每周 5 单降低到 0", "实现订单与支付回调模块，重复回调导致的错单明显减少"),
        ("设计热门商品缓存方案，商品列表接口响应时间降低 70%", "设计热门商品缓存方案，商品列表接口响应时间明显降低"),
        ("重构登录鉴权逻辑，接口越权漏洞从 3 个减少到 0 个", "重构登录鉴权逻辑，接口越权漏洞明显减少"),
    ]),
    ("在线考试系统", ["Django", "Vue", "PostgreSQL"], [
        ("设计试卷、题目、答卷三张核心表，组卷时间从 10 分钟缩短到 1 分钟", "设计试卷、题目、答卷三张核心表，组卷时间明显缩短"),
        ("实现答题断线续答，每 30 秒自动保存，答卷丢失投诉降低 90%", "实现答题断线续答与自动保存，答卷丢失投诉明显降低"),
        ("优化成绩报表导出，导出时间从 40s 降低到 5s", "优化成绩报表导出，导出时间明显降低"),
    ]),
    ("图书馆座位预约小程序", ["Node.js", "MongoDB", "微信小程序"], [
        ("实现座位预约与超时释放，高峰期支撑 500 人同时预约", "实现座位预约与超时释放，高峰期支撑了大量用户同时预约"),
        ("开发签到提醒功能，未签到导致的空占率从 25% 降低到 8%", "开发签到提醒功能，未签到导致的空占率明显降低"),
        ("优化预约查询接口，平均响应时间从 600ms 降低到 150ms", "优化预约查询接口，平均响应时间明显降低"),
    ]),
    ("秒杀系统", ["Spring Boot", "Redis", "RabbitMQ"], [
        ("实现库存预扣与异步下单，压测下单成功率提升到 99.9%", "实现库存预扣与异步下单，压测下单成功率明显提升"),
        ("设计用户限流与重复下单校验，异常请求拦截率达到 98%", "设计用户限流与重复下单校验，异常请求拦截率有所提升"),
        ("优化库存扣减脚本，单机吞吐量从 800 提升到 3000 次每秒", "优化库存扣减脚本，单机吞吐量明显提升"),
    ]),
    ("课程推荐系统", ["Python", "Flask", "scikit-learn"], [
        ("实现基于选课记录的协同过滤推荐，推荐点击率提升 15%", "实现基于选课记录的协同过滤推荐，推荐点击率有所提升"),
        ("设计离线评估流程，3 种方案的召回率对比时间从 1 天缩短到 1 小时", "设计离线评估流程，多种方案的对比时间明显缩短"),
        ("开发推荐接口，平均响应时间降低到 80ms", "开发推荐接口，平均响应时间明显降低"),
    ]),
    ("个人博客系统", ["Go", "Gin", "MySQL"], [
        ("实现文章全文搜索，搜索平均耗时从 800ms 降低到 120ms", "实现文章全文搜索，搜索平均耗时明显降低"),
        ("搭建 CI 流水线，每次发布的时间从 30 分钟缩短到 8 分钟", "搭建 CI 流水线，每次发布的时间明显缩短"),
        ("重构日志与鉴权中间件，重复代码减少 40%", "重构日志与鉴权中间件，重复代码明显减少"),
    ]),
]

UNUSED_SKILLS = ["Kubernetes", "Kafka", "Elasticsearch", "TensorFlow", "Hadoop", "Flink"]   # 底稿的经历里都没出现过

# 语义类注入：接在某条描述后面（"，" + 下面这句）。不带编号、不超长，免得规则通道误打误撞
EXAGGERATION = ["并以实习生身份独立主导了全公司核心交易系统的架构设计", "并一人带领研发团队完成了公司级的技术架构改造",
                "并独自支撑了全公司千万级日活用户的全部业务流量", "并由我一人决定了部门未来三年的技术路线"]
INCOHERENT = ["上线后数据库压力反而翻倍，因此系统性能得到了大幅提升", "改造后接口响应变得更慢，用户体验因此明显变好",
              "新方案让服务器数量增加了两倍，从而节省了大量服务器成本", "由于取消了所有缓存，热点数据的读取速度因此快了很多"]
UNCLEAR = ["这部分工作由项目组共同完成，大家一起推进了上线", "团队整体负责了设计、开发与测试，最终项目顺利交付",
           "我们小组分工协作完成了这一模块，具体由组内同学实现", "该功能由几位同学一起讨论实现，后续也由团队统一维护"]
SUMMARIES = ["对后端开发有浓厚兴趣，习惯先把问题拆清楚再动手，写代码注重可读性和测试。",
             "做事认真，喜欢用数据说话；在团队项目里多次负责需求梳理与进度协调。"]


def make_base(rng: random.Random, index: int) -> dict:
    """一份干净底稿：两段衔接的实习（新的在前）、两个项目、技能栏只列项目技术栈。"""
    roles = rng.sample(sorted(INTERNSHIPS), 2)
    companies = rng.sample(COMPANIES, 2)
    projects = rng.sample(PROJECTS, 2)
    stack = list(dict.fromkeys(s for _, st, _ in projects for s in st))     # 去重保序
    return {
        "name": rng.choice(SURNAMES) + rng.choice(GIVEN), "city": rng.choice(CITIES),
        "school": rng.choice(SCHOOLS),
        # 两段实习：后一段 2025.03 开始，前一段 2025.02 结束，间隔 1 个月
        "work": [{"company": companies[0], "role": roles[0], "date": "2025.03-2025.06", "bullets": INTERNSHIPS[roles[0]]},
                 {"company": companies[1], "role": roles[1], "date": "2024.12-2025.02", "bullets": INTERNSHIPS[roles[1]]}],
        "projects": [{"name": n, "stack": st, "date": d, "bullets": b}
                     for (n, st, b), d in zip(projects, ["2024.09-2024.12", "2024.03-2024.06"])],
        "skills": [f"开发：{'、'.join(stack[:3])}", f"其他：{'、'.join(stack[3:])}"] if len(stack) > 3
        else [f"开发：{'、'.join(stack)}"],
        "summary": SUMMARIES[index % len(SUMMARIES)],
    }


def to_content(base: dict, index: int) -> Content:
    work = [Entry(f"{w['company']} {w['role']}", w["date"], list(w["bullets"])) for w in base["work"]]
    projects = [Entry(p["name"], p["date"], [f"技术栈：{'、'.join(p['stack'])}", *p["bullets"]]) for p in base["projects"]]
    return Content(
        name=base["name"], intent="后端开发实习", phone=f"138-0000-{1000 + index:04d}",
        email=f"eval{index:02d}@example.com", city=base["city"],
        education=[Entry(f"{base['school']} 计算机科学与技术 本科", "2022.09-2026.06", ["GPA 3.6/4.0，专业排名前 15%"])],
        work=work, projects=projects, skills=list(base["skills"]),
        awards=["2023 年 校级一等奖学金", "2024 年 蓝桥杯省赛二等奖"], summary=base["summary"],
    )


def _text(bullet) -> str:
    return bullet if isinstance(bullet, str) else bullet[0]


def variants(base: dict, index: int) -> dict[str, tuple[Content, list[dict]]]:
    """三个版本：(要画的内容, 缺陷清单)。描述在底稿里是 (原句, 去量化说法)，画之前统一换成字符串。"""
    def plain(b: dict) -> dict:
        b = json.loads(json.dumps(b))
        for e in b["work"] + b["projects"]:
            e["bullets"] = [_text(x) for x in e["bullets"]]
        return b

    out: dict[str, tuple[Content, list[dict]]] = {"clean": (to_content(plain(base), index), [])}

    # work[0] 是较近的一段实习（2025.03 起），work[1] 是较早的一段
    # 规则类：较早那段的第 1 条去量化；第一个项目第 1 条加「协助」；技能栏多写一个没用过的技能；较早那段往前挪出空窗
    rule = plain(base)
    dequant = base["work"][1]["bullets"][0][1]
    rule["work"][1]["bullets"][0] = dequant
    weak = "协助" + rule["projects"][0]["bullets"][0]
    rule["projects"][0]["bullets"][0] = weak
    unused = UNUSED_SKILLS[index % len(UNUSED_SKILLS)]
    rule["skills"][0] += f"、{unused}"
    rule["work"][1]["date"] = "2024.05-2024.08"                    # 到 2025.03 空了 7 个月
    out["rule"] = (to_content(rule, index), [
        {"type": "dequant", "expect": "NO_QUANTIFICATION", "anchor": dequant},
        {"type": "weak_verb", "expect": "WEAK_VERB", "anchor": weak},
        {"type": "skill_unused", "expect": "SKILL_PROJECT_MISMATCH", "anchor": unused},
        # 规则把空窗报在开始得较晚的那段经历的标题行上
        {"type": "timeline_gap", "expect": "TIMELINE_ANOMALY",
         "anchor": f"{rule['work'][0]['company']} {rule['work'][0]['role']}"},
    ])

    # 语义类：夸大接在较近那段实习的第 2 条后面；前后矛盾、职责不清分别接在两个项目的第 2 条后面
    sem = plain(base)
    clauses = {"exaggeration": EXAGGERATION[index % 4], "incoherent": INCOHERENT[index % 4],
               "unclear_ownership": UNCLEAR[index % 4]}
    for (key, i), (kind, clause) in zip([("work", 0), ("projects", 0), ("projects", 1)], clauses.items()):
        sem[key][i]["bullets"][1] += f"，{clause}"
    out["semantic"] = (to_content(sem, index), [
        {"type": kind, "expect": kind, "anchor": clause} for kind, clause in clauses.items()])
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gt: dict[str, dict] = {}
    for i in range(N_BASES):
        base = make_base(random.Random(SEED * 100 + i), i)
        for variant, (content, defects) in variants(base, i).items():
            rng = random.Random(SEED * 100 + i)                     # 同一份底稿的三个版本用同一套版式参数
            style = make_style(rng)
            # 版面不是这里的被测对象：字号、行距固定得紧凑一点，保证注入了句子的版本也放得下一页
            style.size, style.lead, style.section_gap, style.margin = 10, 14.5, 8, 42
            cv = draw_single(content, style, rng)
            drawn = squash("".join(cv.lines))                       # 折行处的空格被去掉了，两边都去空白再比
            if cv.bottom > H - 36 or any(squash(d["anchor"]) not in drawn for d in defects):
                raise RuntimeError(f"底稿 {i} 的 {variant} 版超出一页，或缺陷没画全")
            name = f"{i + 1:02d}-{variant}.pdf"
            cv.doc.save(OUT_DIR / name)
            cv.doc.close()
            gt[name] = {"base": i + 1, "variant": variant, "defects": defects}
    (OUT_DIR / "gt.json").write_text(json.dumps(gt, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"生成 {len(gt)} 份 → {OUT_DIR}")


if __name__ == "__main__":
    main()
