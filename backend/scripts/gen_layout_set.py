"""生成版面合成集：python scripts/gen_layout_set.py

20 份虚构的简历内容 × 6 种版式 = 120 份单页 PDF，写进 data/layout_set/（不进仓库，随时可以重新生成）：
  single 单栏 · double 两栏（页顶姓名通栏）· sidebar 左侧边栏（一半带底色）· table 表格型（整页带边框的表格）
  timeline 时间轴（单栏，经历的日期单独成左列，和标题在同一行）· borderless 表格型去掉边框（只靠对齐）
标准答案在同目录的 gt.json：{文件名: {"layout": 版式, "lines": [按正确阅读顺序排好的每一段文字]}}。
"一段文字"就是生成时画出去的一次：一行正文、折行后的一截、右对齐的日期、表格里一格中的一行。
画的顺序就是阅读顺序（先左栏后右栏；表格逐行、一行里从左到右）。

字号、页边距、行距、栏宽、项目符号、标题下划线在范围内随机，随机种子固定，每次生成的结果完全一样。
中文用内置宋体，英文和数字用 Helvetica，同一行里混排（和真实简历一样是比例宽度）。
内容超出一页时逐条删掉描述再重画，所以同一份内容在不同版式里可能少一两条。
评测见 scripts/eval_layout.py。
"""
from __future__ import annotations

import json
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402

SEED = 2026
N_CONTENTS = 20
LAYOUTS = ("single", "double", "sidebar", "table", "timeline", "borderless")
OUT_DIR = settings.DATA_DIR / "layout_set"
W, H = pymupdf.paper_size("a4")
CJK_FONT, LATIN_FONT = "china-s", "helv"

# ───────────────────────── 内容（全部虚构） ─────────────────────────

SURNAMES = "张王李赵刘陈杨黄周吴徐孙马朱胡郭何林罗高"
GIVEN = ["子涵", "浩然", "雨桐", "思远", "一鸣", "欣怡", "俊杰", "梓萱", "宇航", "佳琪", "明轩", "诗雨", "嘉豪", "若曦"]
CITIES = ["江城", "北岭", "南湖", "东川", "青州", "云岭"]
SCHOOLS = ["江城大学", "北岭理工大学", "南湖师范大学", "东川科技大学", "西津工业大学", "青州大学", "云岭大学", "海滨理工学院"]
MAJORS = ["计算机科学与技术", "软件工程", "数据科学与大数据技术", "人工智能", "信息管理与信息系统", "网络工程"]
COURSES = ["主修课程：数据结构、操作系统、计算机网络、数据库原理", "主修课程：机器学习、概率论与数理统计、线性代数、算法设计",
           "主修课程：Java 程序设计、软件工程导论、Web 开发技术、编译原理"]
COMPANIES = ["星河科技", "远帆网络", "青木数据", "蓝鲸软件", "北辰智能", "山海互娱", "云杉信息"]
ROLES = {
    "后端开发实习生": [
        "参与订单服务的接口开发，使用 Spring Boot 与 MyBatis 完成退款流程改造",
        "为商品详情接口加入 Redis 缓存，接口平均响应时间从 120ms 降到 35ms",
        "编写单元测试 60 余个，核心模块测试覆盖率提升到 80%",
        "排查线上慢查询 12 条，通过加索引和改写 SQL 把最慢的查询从 2s 降到 200ms",
        "参与消息队列的接入，用 RabbitMQ 把下单后的通知改为异步发送",
    ],
    "前端开发实习生": [
        "负责运营后台 6 个页面的开发，使用 Vue 3 与 Element Plus 实现表单和表格组件",
        "把首页的图片改为懒加载并拆分打包，首屏加载时间从 3.2s 降到 1.6s",
        "封装通用的请求与错误提示模块，被团队 4 个项目复用",
        "配合后端联调 20 余个接口，整理接口文档并补充类型定义",
    ],
    "数据分析实习生": [
        "用 SQL 与 Python 整理每周的用户留存数据，搭建自动生成的周报",
        "分析新用户注册流程的转化漏斗，找出流失最多的两步并提出改版建议",
        "用 Pandas 清洗 30 万条订单数据，完成分地区的销售对比分析",
        "参与 A/B 实验的数据核对，编写实验结果的统计检验脚本",
    ],
    "测试开发实习生": [
        "使用 Pytest 编写接口自动化用例 150 余条，接入每日构建流程",
        "搭建性能测试环境，用 JMeter 压测下单接口并输出瓶颈分析报告",
        "维护测试数据构造工具，新版本回归时间从 2 天缩短到半天",
    ],
    "算法实习生": [
        "参与商品推荐模型的特征工程，新增 8 个用户行为特征",
        "复现两篇排序模型论文，在内部数据集上对比效果并整理实验记录",
        "用 PyTorch 训练文本分类模型，验证集准确率从 86% 提升到 91%",
    ],
}
PROJECTS = [
    ("校园二手交易平台", "Spring Boot、MySQL、Redis", [
        "负责订单模块与支付回调，回调先验签，再用订单状态做幂等判断",
        "用 Redis 缓存热门商品，结合过期时间与主动删除保证缓存和数据库一致",
        "使用 JWT 完成登录鉴权，对管理接口做了基于角色的权限控制"]),
    ("在线考试系统", "Django、Vue、PostgreSQL", [
        "设计试卷、题目、答卷三张核心表，支持随机组卷与自动判分",
        "实现考试倒计时与断线续答，答题记录每 30 秒自动保存",
        "用 Celery 异步生成成绩报表，教师端导出时间从 40s 降到 5s"]),
    ("图书馆座位预约小程序", "微信小程序、Node.js、MongoDB", [
        "实现座位预约、签到与超时释放，高峰期支持 500 人同时预约",
        "用定时任务扫描未签到的预约，15 分钟未签到自动释放座位",
        "接入消息订阅，在预约开始前 10 分钟提醒用户"]),
    ("基于 Redis 的秒杀系统", "Spring Boot、Redis、RabbitMQ", [
        "库存预扣放在 Redis 中用 Lua 脚本完成，避免超卖",
        "下单请求进入消息队列削峰，由消费者异步创建订单",
        "对同一用户加限流与重复下单校验，压测下单成功率 99.9%"]),
    ("课程推荐系统", "Python、Flask、scikit-learn", [
        "基于选课记录构建用户与课程的共现矩阵，实现协同过滤推荐",
        "设计离线评估流程，用召回率与覆盖率比较三种推荐方案",
        "提供推荐接口与简单的前端页面，供同学试用并收集反馈"]),
    ("实验室设备管理系统", "Java、Spring Boot、Vue", [
        "实现设备借用、归还与维修登记，借用记录可按学期导出",
        "设计审批流程，借用高价值设备需要导师在线审批",
        "用定时任务提醒逾期未还，逾期率从 20% 降到 5%"]),
    ("个人博客系统", "Go、Gin、MySQL", [
        "实现文章发布、标签分类与全文搜索，支持 Markdown 编辑",
        "用中间件统一处理日志、鉴权与异常，接口返回格式保持一致",
        "部署在云服务器上，用 Nginx 做反向代理并配置 HTTPS"]),
    ("简历关键词提取工具", "Python、jieba、FastAPI", [
        "对上传的简历分词并匹配技能词典，输出技能列表与出现位置",
        "对比词典匹配与 TF-IDF 两种方案，整理准确率对比表",
        "封装为接口供课程设计小组调用，平均处理一份简历 0.3s"]),
]
SKILLS = ["编程语言：Java、Python、Go", "编程语言：Python、JavaScript、TypeScript", "数据库：MySQL、Redis、MongoDB",
          "框架：Spring Boot、MyBatis、Django", "前端：Vue 3、React、Element Plus", "工具：Git、Docker、Linux 常用命令",
          "数据分析：Pandas、NumPy、Matplotlib", "机器学习：PyTorch、scikit-learn", "测试：Pytest、JMeter、Postman",
          "英语：CET-6，能阅读英文技术文档"]
AWARDS = ["蓝桥杯省赛二等奖", "全国大学生数学建模竞赛省一等奖", "校级一等奖学金", "ACM 程序设计校赛银奖",
          "互联网+ 创新创业大赛校赛金奖", "优秀学生干部", "计算机设计大赛省三等奖", "校级优秀毕业设计"]
SUMMARIES = [
    "对后端开发有浓厚兴趣，习惯先把问题拆清楚再动手，写代码注重可读性和测试。",
    "学习能力强，能较快上手新的框架；做过多个完整的课程项目，熟悉从设计到部署的流程。",
    "做事认真，喜欢用数据说话；在团队项目里多次负责需求梳理与进度协调。",
    "热爱编程，长期在 GitHub 上记录学习笔记，乐于和同学分享踩过的坑。",
]


@dataclass
class Entry:
    title: str
    date: str
    bullets: list[str] = field(default_factory=list)


@dataclass
class Content:
    name: str
    intent: str
    phone: str
    email: str
    city: str
    education: list[Entry]
    work: list[Entry]
    projects: list[Entry]
    skills: list[str]
    awards: list[str]
    summary: str

    def trim(self) -> bool:
        """删掉一条描述（从描述最多的那条经历里删），删不动了返回 False。"""
        entries = [e for e in self.work + self.projects + self.education if e.bullets]
        if entries:
            max(entries, key=lambda e: len(e.bullets)).bullets.pop()
            return True
        if len(self.skills) > 2:
            self.skills.pop()
            return True
        return False


def make_content(rng: random.Random, index: int) -> Content:
    def period(start_year: int, start_month: int, months: int) -> str:
        end = start_year * 12 + start_month - 1 + months
        return f"{start_year}.{start_month:02d}-{end // 12}.{end % 12 + 1:02d}"

    school, major = rng.choice(SCHOOLS), rng.choice(MAJORS)
    education = [Entry(f"{school} {major} 本科", "2022.09-2026.06",
                       [f"GPA {rng.choice(['3.5', '3.6', '3.7', '3.8'])}/4.0，专业排名前 {rng.choice([5, 10, 15, 20])}%",
                        rng.choice(COURSES)][:rng.randint(1, 2)])]
    if rng.random() < 0.3:
        education.insert(0, Entry(f"{rng.choice(SCHOOLS)} {major} 硕士", "2026.09-2029.06", []))

    roles = rng.sample(sorted(ROLES), rng.randint(1, 2))
    work = []
    for k, role in enumerate(roles):
        work.append(Entry(f"{rng.choice(COMPANIES)} {role}", period(2025 - k, rng.choice([1, 3, 7]), rng.randint(2, 5)),
                          rng.sample(ROLES[role], rng.randint(2, 3))))
    projects = []
    for k, (name, stack, bullets) in enumerate(rng.sample(PROJECTS, 2)):
        projects.append(Entry(name, period(2024 - k, rng.choice([3, 9]), rng.randint(2, 4)),
                              [f"技术栈：{stack}"] + rng.sample(bullets, rng.randint(1, 2))))
    awards = [f"{2022 + k} 年 {a}" for k, a in enumerate(rng.sample(AWARDS, rng.randint(2, 3)))]
    return Content(
        name=rng.choice(SURNAMES) + rng.choice(GIVEN),
        intent=rng.choice(roles).replace("实习生", "实习"),
        phone=f"138-0000-{rng.randint(1000, 9999)}",
        email=f"candidate{index:02d}@example.com",
        city=rng.choice(CITIES),
        education=education, work=work, projects=projects,
        skills=rng.sample(SKILLS, rng.randint(3, 4)), awards=awards, summary=rng.choice(SUMMARIES),
    )


# ───────────────────────── 画布 ─────────────────────────

_TOKEN = re.compile(r"[\x21-\x7e]+|\s+|.")  # 一个英文单词 / 一段空白 / 一个其他字符


def _runs(s: str) -> list[tuple[str, str]]:
    """把一行拆成连续的"英文数字段"和"中文段"，各自用对应的字体画。"""
    return [(m.group(0), LATIN_FONT if m.group(0).isascii() else CJK_FONT)
            for m in re.finditer(r"[\x00-\x7f]+|[^\x00-\x7f]+", s)]


def text_width(s: str, size: float) -> float:
    return sum(pymupdf.get_text_length(run, font, size) for run, font in _runs(s))


def wrap(s: str, width: float, size: float) -> list[str]:
    """按宽度折行：英文按单词断，中文按字断。返回的每一截都去掉了首尾空白。"""
    pieces, cur = [], ""
    for token in _TOKEN.findall(s):
        if cur.strip() and text_width(cur + token, size) > width:
            pieces.append(cur.strip())
            cur = token.lstrip()
        else:
            cur += token
    if cur.strip():
        pieces.append(cur.strip())
    return pieces


@dataclass
class Style:
    size: float
    lead: float           # 行距
    head_size: float
    name_size: float
    margin: float
    section_gap: float
    underline: bool
    bullet: str           # "● " / "· " / "- " / "num"（• 用内置字体画出来抽回来是 ·，所以不用）
    hanging: bool         # 折行是否和项目符号后的文字对齐


def make_style(rng: random.Random) -> Style:
    size = rng.choice([9.5, 10, 10.5])
    return Style(size=size, lead=round(size * rng.uniform(1.45, 1.65), 1), head_size=size + rng.choice([2, 3]),
                 name_size=rng.choice([18, 20, 22]), margin=rng.choice([36, 42, 48, 54]),
                 section_gap=round(size * rng.uniform(0.8, 1.2), 1), underline=rng.random() < 0.5,
                 bullet=rng.choice(["● ", "· ", "- ", "num"]), hanging=rng.random() < 0.5)


class Canvas:
    """画一页，同时按画的顺序记下标准答案。"""

    def __init__(self, style: Style):
        self.doc = pymupdf.open()
        self.page = self.doc.new_page(width=W, height=H)
        self.st = style
        self.lines: list[str] = []
        self.bottom = 0.0
        self.date_col = 0.0   # 时间轴版式：日期单独成左列的宽度；0 = 日期右对齐在标题行末尾

    def text(self, x: float, y: float, s: str, size: float | None = None) -> None:
        size = size or self.st.size
        for run, font in _runs(s):
            self.page.insert_text((x, y), run, fontsize=size, fontname=font)
            x += pymupdf.get_text_length(run, font, size)
        self.lines.append(s.strip())
        self.bottom = max(self.bottom, y + size * 0.3)

    def heading(self, x0: float, x1: float, y: float, title: str) -> float:
        """章节标题，返回下一行的基线。"""
        y += self.st.section_gap + self.st.head_size
        self.text(x0, y, title, self.st.head_size)
        if self.st.underline:
            self.page.draw_line((x0, y + 4), (x1, y + 4), color=(0.3, 0.3, 0.3), width=0.6)
        return y + self.st.lead + (4 if self.st.underline else 0)

    def paragraph(self, x0: float, x1: float, y: float, s: str, prefix: str = "") -> float:
        indent = text_width(prefix, self.st.size) if self.st.hanging else 0
        for k, piece in enumerate(wrap(prefix + s, x1 - x0, self.st.size) if not indent
                                  else self._hanging(prefix + s, x1 - x0, indent)):
            self.text(x0 + (indent if k else 0), y, piece)
            y += self.st.lead
        return y

    def _hanging(self, s: str, width: float, indent: float) -> list[str]:
        first = wrap(s, width, self.st.size)[0]
        rest = s[len(first):].strip()  # wrap 只会在空白处去掉字符，首截之后的原文从这里接上
        return [first] + (wrap(rest, width - indent, self.st.size) if rest else [])

    def entry(self, x0: float, x1: float, y: float, e: Entry) -> float:
        """经历：标题 + 右对齐的日期（放不下就另起一行），再是各条描述。
        时间轴版式：日期画在左列、标题和描述画在右边，日期和标题在同一行（先画日期：按行读是先左后右）。"""
        date_w = text_width(e.date, self.st.size)
        if self.date_col:
            self.text(x0, y, e.date)
            x0 += self.date_col
            self.text(x0, y, e.title)
        elif text_width(e.title, self.st.size) + date_w + 12 <= x1 - x0:
            self.text(x0, y, e.title)
            self.text(x1 - date_w, y, e.date)
        else:
            self.text(x0, y, e.title)
            y += self.st.lead
            self.text(x0, y, e.date)
        y += self.st.lead
        for k, b in enumerate(e.bullets):
            prefix = f"{k + 1}. " if self.st.bullet == "num" else self.st.bullet
            y = self.paragraph(x0, x1, y, b, prefix)
        return y + self.st.lead * 0.3

    def section(self, x0: float, x1: float, y: float, title: str, c: Content) -> float:
        y = self.heading(x0, x1, y, title)
        if title == "教育背景":
            for e in c.education:
                y = self.entry(x0, x1, y, e)
        elif title == "实习经历":
            for e in c.work:
                y = self.entry(x0, x1, y, e)
        elif title == "项目经历":
            for e in c.projects:
                y = self.entry(x0, x1, y, e)
        elif title == "专业技能":
            for s in c.skills:
                y = self.paragraph(x0, x1, y, s)
        elif title == "获奖情况":
            for s in c.awards:
                y = self.paragraph(x0, x1, y, s)
        else:
            y = self.paragraph(x0, x1, y, c.summary)
        return y


# ───────────────────────── 版式 ─────────────────────────


def draw_single(c: Content, st: Style, rng: random.Random, date_col: float = 0.0) -> Canvas:
    cv = Canvas(st)
    cv.date_col = date_col
    x0, x1 = st.margin, W - st.margin
    y = st.margin + st.name_size
    cv.text((W - text_width(c.name, st.name_size)) / 2, y, c.name, st.name_size)
    contact = f"电话：{c.phone}  |  邮箱：{c.email}  |  {c.city}"
    y += st.lead * 1.6
    cv.text((W - text_width(contact, st.size)) / 2, y, contact)
    for title in ["教育背景", "实习经历", "项目经历", "专业技能", "获奖情况", "自我评价"]:
        y = cv.section(x0, x1, y, title, c)
    return cv


def draw_double(c: Content, st: Style, rng: random.Random) -> Canvas:
    cv = Canvas(st)
    gutter = rng.choice([20, 24, 30])
    col = (W - 2 * st.margin - gutter) / 2
    y = st.margin + st.name_size
    cv.text((W - text_width(c.name, st.name_size)) / 2, y, c.name, st.name_size)
    contact = f"电话：{c.phone}  |  邮箱：{c.email}"
    y += st.lead * 1.6
    cv.text((W - text_width(contact, st.size)) / 2, y, contact)
    top = y + st.lead * 0.5
    left, right = (st.margin, st.margin + col), (st.margin + col + gutter, W - st.margin)
    y = top
    for title in ["教育背景", "专业技能", "获奖情况", "自我评价"]:
        y = cv.section(*left, y, title, c)
    y = top
    for title in ["实习经历", "项目经历"]:
        y = cv.section(*right, y, title, c)
    return cv


def draw_sidebar(c: Content, st: Style, rng: random.Random) -> Canvas:
    cv = Canvas(st)
    side = rng.choice([150, 165, 180])
    gutter = rng.choice([20, 26])
    if rng.random() < 0.5:  # 侧边栏底色：find_tables 看到的只是一个格子，不能把它当成表格
        cv.page.draw_rect(pymupdf.Rect(0, 0, st.margin + side + gutter / 2, H), color=None, fill=(0.92, 0.94, 0.96))
    left, right = (st.margin, st.margin + side), (st.margin + side + gutter, W - st.margin)
    y = st.margin + st.name_size
    cv.text(left[0], y, c.name, st.name_size)
    y += st.lead * 1.4
    for s in [f"求职意向：{c.intent}", f"电话：{c.phone}", c.email, f"城市：{c.city}"]:
        y = cv.paragraph(*left, y, s)
    for title in ["专业技能", "获奖情况"]:
        y = cv.section(*left, y, title, c)
    y = st.margin
    for title in ["教育背景", "实习经历", "项目经历", "自我评价"]:
        y = cv.section(*right, y, title, c)
    return cv


def draw_timeline(c: Content, st: Style, rng: random.Random) -> Canvas:
    """单栏，但经历的日期单独成左列、和标题在同一行（时间轴）。技能、获奖、自我评价照常通栏。"""
    widest = max(text_width(e.date, st.size) for e in c.education + c.work + c.projects)
    return draw_single(c, st, rng, date_col=widest + rng.choice([16, 24, 32]))


def draw_table(c: Content, st: Style, rng: random.Random, borders: bool = True) -> Canvas:
    """表格型：个人信息 4 列、教育 4 列（带表头），其余章节是"左列章节名 | 右列内容"的两列表。
    一半的文档把每段经历放在单独一行、章节名竖着合并成一格。borders=False 时不画边框（只靠对齐）。"""
    cv = Canvas(st)
    pad, x0, x1 = 5, st.margin, W - st.margin
    title = "个人简历"
    y = st.margin + st.name_size
    cv.text((W - text_width(title, st.name_size)) / 2, y, title, st.name_size)
    y += 14

    def grid(y: float, widths: list[float], rows: list[list[list[str] | None]]) -> float:
        """rows 里每格是这一格的若干行文字；None 表示被上一行同一列的格子竖着合并了。按行、从左到右画。"""
        heights = [max((len(cell) for cell in row if cell is not None), default=1) * st.lead + 2 * pad for row in rows]
        tops = [y + sum(heights[:i]) for i in range(len(rows))]
        for i, row in enumerate(rows):
            x = x0
            for j, (cell, w) in enumerate(zip(row, widths)):
                if cell is not None:
                    span = 1
                    while i + span < len(rows) and rows[i + span][j] is None:
                        span += 1
                    if borders:
                        cv.page.draw_rect(pymupdf.Rect(x, tops[i], x + w, tops[i] + sum(heights[i:i + span])),
                                          color=(0, 0, 0), width=0.6)
                    for k, s in enumerate(cell):
                        cv.text(x + pad, tops[i] + pad + st.size + k * st.lead, s)
                x += w
        return tops[-1] + heights[-1]

    full = x1 - x0
    label_w = rng.choice([80, 90])
    info_w = [label_w, full / 2 - label_w, label_w, full / 2 - label_w]
    y = grid(y, info_w, [[["姓名"], [c.name], ["求职意向"], [c.intent]],
                         [["电话"], [c.phone], ["邮箱"], [c.email]]]) + 12
    edu_w = [full * 0.26, full * 0.24, full * 0.34, full * 0.16]
    edu_rows = [[["时间"], ["学校"], ["专业"], ["学历"]]]
    for e in c.education:
        school, major, degree = e.title.split()
        edu_rows.append([[e.date], [school], wrap(major, edu_w[2] - 2 * pad, st.size), [degree]])
    y = grid(y, edu_w, edu_rows) + 12

    content_w = full - label_w - 2 * pad
    merged = rng.random() < 0.5

    def lines_of(e: Entry) -> list[str]:
        out = wrap(f"{e.title}（{e.date}）", content_w, st.size)
        for k, b in enumerate(e.bullets):
            out += wrap(f"{k + 1}. {b}", content_w, st.size)
        return out

    rows: list[list[list[str] | None]] = []
    for label, entries in [("实习经历", c.work), ("项目经历", c.projects)]:
        if merged:
            rows += [[[label] if k == 0 else None, lines_of(e)] for k, e in enumerate(entries)]
        else:
            rows.append([[label], [s for e in entries for s in lines_of(e)]])
    rows.append([["专业技能"], [s for sk in c.skills for s in wrap(sk, content_w, st.size)]])
    rows.append([["获奖情况"], [s for a in c.awards for s in wrap(a, content_w, st.size)]])
    rows.append([["自我评价"], wrap(c.summary, content_w, st.size)])
    grid(y, [label_w, full - label_w], rows)
    return cv


DRAW = {"single": draw_single, "double": draw_double, "sidebar": draw_sidebar, "table": draw_table,
        "timeline": draw_timeline, "borderless": lambda c, st, rng: draw_table(c, st, rng, borders=False)}


def render(layout: str, content: Content, seed: int) -> Canvas:
    """画不下一页就删一条描述重画。每次重画用同一个随机种子，版式参数不变。"""
    while True:
        rng = random.Random(seed)
        cv = DRAW[layout](content, make_style(rng), rng)
        if cv.bottom <= H - 36:
            return cv
        cv.doc.close()
        if not content.trim():
            raise RuntimeError(f"{layout} 版式删到最少还是超出一页")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gt: dict[str, dict] = {}
    for i in range(N_CONTENTS):
        for layout in LAYOUTS:
            content = make_content(random.Random(SEED * 1000 + i), i)  # 每种版式都从同一份内容开始删
            cv = render(layout, content, SEED * 1000 + i * 10 + LAYOUTS.index(layout))
            name = f"{i + 1:02d}-{layout}.pdf"
            cv.doc.save(OUT_DIR / name)
            cv.doc.close()
            gt[name] = {"layout": layout, "lines": cv.lines}
    (OUT_DIR / "gt.json").write_text(json.dumps(gt, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"生成 {len(gt)} 份 → {OUT_DIR}")


if __name__ == "__main__":
    main()
