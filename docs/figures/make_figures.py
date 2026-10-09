"""论文用图：系统架构、产品流程、图 A、图 B、E-R 图，以及四张评测图。只用 Python 标准库。

    python docs/figures/make_figures.py

输出到本目录：每张图一份 SVG（矢量，Word 里「插入 → 图片」可以直接插，放大不糊）和一份 2 倍分辨率的 PNG。
PNG 用本机 Chrome / Edge 的无头模式截出来；找不到浏览器就只出 SVG。
风格：白底黑字、只用灰度（黑白打印也分得清）；调用模型的节点灰底，纯函数白底，外部服务虚线框。
内容的出处：流程和节点 docs/06-workflows.md，外键 backend/sql/schema.sql，评测数字 docs/05-evaluation-and-plan.md 5.2–5.4。
那几处改了，这里要跟着改。
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
FONT = "Microsoft YaHei, SimHei, PingFang SC, sans-serif"  # 学校要求图里用宋体就改成 "SimSun, serif"
MONO = "Consolas, Menlo, monospace"
INK, INK2, LINE = "#1a1a1a", "#555555", "#333333"
LLM_FILL, GROUP_FILL, GROUP2_FILL, HEAD_FILL = "#d9d9d9", "#f2f2f2", "#e6e6e6", "#e6e6e6"
SERIES = ["#ffffff", "#a6a6a6", "#3d3d3d"]  # 柱状图三组：白 / 浅灰 / 深灰


def text_width(s: str, size: float) -> float:
    """估算宽度：中文按一个字号，英文、数字、空格按 0.55 个"""
    return sum(size if ord(ch) > 0x2E7F else size * 0.55 for ch in s)


class Fig:
    def __init__(self, name: str, w: int, h: int):
        self.name, self.w, self.h, self.els = name, w, h, []

    # ── 基本图元 ──
    def rect(self, x, y, w, h, fill="#fff", dash=False, r=8, stroke=LINE, sw=1.4):
        d = ' stroke-dasharray="6 4"' if dash else ""
        self.els.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r}" fill="{fill}" '
                        f'stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def text(self, x, y, s, size=13, weight=400, color=INK, anchor="middle", mono=False, rotate=0):
        fam = f' font-family="{MONO}"' if mono else ""
        rot = f' transform="rotate({rotate} {x:.1f} {y:.1f})"' if rotate else ""
        self.els.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" fill="{color}" '
                        f'text-anchor="{anchor}"{fam}{rot}>{escape(s)}</text>')

    def line(self, pts, arrow=True, both=False, dash=False, color=LINE, sw=1.4):
        p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        m = (' marker-end="url(#ah)"' if arrow else "") + (' marker-start="url(#ah)"' if both else "")
        d = ' stroke-dasharray="6 4"' if dash else ""
        self.els.append(f'<polyline points="{p}" fill="none" stroke="{color}" stroke-width="{sw}"{m}{d}/>')

    def circle(self, cx, cy, label, r=17):
        self.els.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{INK}"/>')
        self.text(cx, cy + 4, label, 11, 700, "#fff")

    # ── 组合 ──
    def box(self, x, y, w, h, title, lines=(), code=None, fill="#fff", dash=False, sw=1.4, tsize=14, dsize=12):
        """粗体标题 + 灰色说明若干行 + 代码里的名字（等宽字），整块在框里上下居中"""
        self.rect(x, y, w, h, fill, dash, sw=sw)
        rows = [(title, tsize, 700, INK, False)] + [(s, dsize, 400, INK2, False) for s in lines]
        if code:
            rows.append((code, 11.5, 400, INK2, True))
        heights = [tsize + 6] + [dsize + 5] * (len(rows) - 1)
        cy = y + (h - sum(heights)) / 2
        for (s, size, weight, color, mono), hh in zip(rows, heights):
            cy += hh
            self.text(x + w / 2, cy - 5, s, size, weight, color, mono=mono)

    def group(self, x, y, w, h, title, fill=GROUP_FILL, dash=False, anchor="start", stroke=LINE):
        self.rect(x, y, w, h, fill, dash, r=12, stroke=stroke)
        self.text(x + 16 if anchor == "start" else x + w - 16, y + 23, title, 14, 700, INK, anchor)

    def legend(self, x, y, items, gap=36):
        """items: [(填充, 标签, 样式)]，样式：None / "dash" / "thick" """
        for fill, label, style in items:
            self.rect(x, y - 12, 26, 16, fill, dash=style == "dash", r=4, sw=2.6 if style == "thick" else 1.4)
            self.text(x + 34, y + 1, label, 12.5, 400, INK, "start")
            x += 34 + text_width(label, 12.5) + gap

    def save(self, browser: str | None) -> None:
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" '
               f'font-family="{FONT}"><defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
               f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{LINE}"/></marker></defs>'
               f'<rect width="{self.w}" height="{self.h}" fill="#fff"/>' + "".join(self.els) + "</svg>\n")
        path = HERE / f"{self.name}.svg"
        path.write_text(svg, encoding="utf-8", newline="")
        if browser:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
                subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={profile}",
                                "--force-device-scale-factor=2", f"--window-size={self.w},{self.h}",
                                f"--screenshot={path.with_suffix('.png')}", path.as_uri()],
                               check=True, capture_output=True, timeout=120)
        print(path.name, "+ png" if browser else "")


def find_browser() -> str | None:
    names = [shutil.which(n) for n in ("chrome", "google-chrome", "chromium", "msedge")]
    paths = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
             r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
             r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    return next((c for c in names + paths if c and Path(c).exists()), None)


# ═════════════════════════════ 图 1 系统架构 ═════════════════════════════
def fig_architecture() -> Fig:
    f = Fig("图1-系统架构", 1400, 930)
    f.box(40, 24, 1320, 72, "浏览器 · 前端单页应用（React 18 + TypeScript + Vite）",
          ["工作台（选方向 → 选岗位 → 选简历 → 投递）· 初筛结果与原文高亮 · 模拟面试 · 我的投递"], tsize=16, dsize=13)
    f.line([(508, 96), (508, 162)], both=True)
    f.text(518, 117, "HTTP 接口 / SSE 流式推送", 12, 400, INK2, "start")

    f.rect(24, 128, 1352, 680, "none", dash=True, r=14, stroke="#777")
    f.text(1360, 150, "Docker Compose（本机一条命令部署）", 13, 400, INK2, "end")
    f.box(48, 164, 920, 58, "Nginx", ["前端静态文件 · /api 反向代理（关闭缓冲，流式输出不被攒包）"], dsize=13)
    f.line([(508, 222), (508, 250)])

    f.group(48, 250, 920, 540, "后端 · FastAPI（Python 3.13，uvicorn 单进程）")
    f.box(72, 290, 872, 56, "接口层 api/", ["认证 · 简历 · 岗位 · 投递 · 具体建议 · 模拟面试 · 进度推送（SSE）"], dsize=13)
    f.line([(508, 346), (508, 362)])
    f.box(72, 362, 872, 56, "服务层 services/", ["读写数据库 · 后台任务 · 跑图并把每一步转成进度 · 中断任务清理"], dsize=13)
    f.line([(508, 418), (508, 434)])
    f.group(72, 434, 872, 266, "领域层（纯数据进出，不碰数据库）", GROUP2_FILL)
    f.box(92, 468, 832, 56, "parser/ 简历解析",
          ["PyMuPDF 抽取 → 分栏 / 表格 / 时间轴 → 章节识别 → 个人信息掩码 → 结构化（模型只回块编号）"], dsize=13)
    f.box(92, 538, 410, 56, "图 A · 投递流水线（LangGraph）", ["诊断子图 ∥ 匹配子图（并行）→ 初筛"], dsize=13)
    f.box(514, 538, 410, 56, "图 B · 模拟面试（LangGraph）", ["定话题 → 出题 → 等回答（interrupt）→ 评分 → 追问 / 换题"], dsize=13)
    mods = [("diagnose/ 诊断", "7 条规则 + 模型审阅"), ("matching/ 匹配", "规则先判 + 全文判断"),
            ("interview/ 面试", "话题 · 评分 · 追问策略"), ("rewrite/ 具体建议", "流式生成 + 数字复检"),
            ("domains/ 领域包", "计算机 / 运营 / 财会")]
    mw = (832 - 4 * 12) / 5
    for i, (t, d) in enumerate(mods):
        f.box(92 + i * (mw + 12), 608, mw, 76, t, [d])
    f.line([(508, 700), (508, 716)])
    f.box(72, 716, 284, 58, "retrieval/ 面经检索", ["切段 → 向量召回 → 重排取前 3 段"])
    f.box(366, 716, 284, 58, "证据校验 locate_span", ["模型引用的原文必须逐字找得到"])
    f.box(660, 716, 284, 58, "llm/ 模型调用唯一出口", ["缓存 · 限流 · 记账 · 校验失败带原因重试"])

    f.group(1000, 250, 352, 540, "存储")
    f.rect(1016, 290, 320, 128)
    f.text(1176, 324, "MySQL 8.0", 16, 700)
    for i, s in enumerate(["11 张表：用户、简历与解析块、", "诊断与问题、岗位、投递、技能词典、", "面试与问答、模型调用审计"]):
        f.text(1176, 352 + i * 19, s, 12, 400, INK2)
    f.box(1016, 434, 320, 74, "Redis", ["模型结果缓存 · 限流 · 进度推送（发布 / 订阅）"], tsize=15)
    f.box(1016, 524, 320, 74, "Chroma（嵌入式）", ["面经切段的向量（面经超过 3000 字才用）"], tsize=15)
    f.box(1016, 614, 320, 74, "SQLite 文件", ["图 B 检查点：停下等回答时保存状态"], tsize=15)
    f.text(1176, 724, "Chroma、SQLite 和上传的 PDF", 12, 400, INK2)
    f.text(1176, 742, "都在后端的数据卷里", 12, 400, INK2)
    for y in (354, 471, 561, 651):
        f.line([(968, y), (1016, y)], both=True)

    f.line([(760, 774), (760, 846)])
    f.text(768, 840, "HTTPS", 12, 400, INK2, "start")
    f.line([(900, 774), (900, 830), (1134, 830), (1134, 846)])
    f.text(1017, 825, "HTTPS", 12, 400, INK2)
    f.box(480, 846, 560, 58, "DeepSeek API · deepseek-chat", ["诊断审阅 · 匹配判断 · JD 拆解 · 具体建议 · 面试出题与评分"],
          dash=True, tsize=15, dsize=13)
    f.box(1056, 846, 296, 58, "硅基流动 API", ["bge-m3 向量 · bge-reranker 重排"], dash=True, tsize=15)
    f.text(72, 880, "外部模型服务（全部走 API，无本地模型）", 13, 400, INK2, "start")
    return f


# ═════════════════════════════ 图 2 产品流程 ═════════════════════════════
def fig_product_flow() -> Fig:
    f = Fig("图2-产品流程", 1400, 600)
    f.box(40, 40, 210, 90, "① 选求职方向", ["计算机 / 运营 / 财会金融", "决定模板、诊断标准和面试官"])
    f.box(290, 40, 210, 90, "② 选目标岗位", ["粘贴招聘 JD，自动拆成要求", "或选这个方向的内置模板"])
    f.box(540, 40, 210, 90, "③ 选简历", ["上传 PDF（后台解析）", "或用已经上传过的"])
    f.box(790, 40, 260, 90, "投递：后台跑图 A", ["等解析完 → 诊断 ∥ 匹配 → 初筛", "每一步的进度实时推送"], fill=LLM_FILL)
    f.box(1090, 40, 270, 90, "④ 初筛结果", ["匹配度、四项分、是否过线", "单独网址，刷新不丢"])
    for x1, x2 in ((250, 290), (500, 540), (750, 790), (1050, 1090)):
        f.line([(x1, 85), (x2, 85)])

    f.box(700, 250, 310, 90, "哪里不符合（没过初筛时重点看）", ["对照岗位的差距 + 简历自身的问题", "点一条 → 原文高亮 + 现场生成具体建议"])
    f.box(1090, 250, 270, 90, "⑤ 面试准备", ["可贴面经 / 公司介绍（选填）", "创建时定好 5 个话题"])
    f.line([(1225, 130), (1225, 250)])
    f.text(1233, 195, "通过：正常模式", 12.5, 400, INK, "start")
    f.line([(1110, 130), (1110, 190), (855, 190), (855, 250)])
    f.text(980, 183, "没通过", 12.5, 400, INK)
    f.line([(1010, 295), (1090, 295)])
    f.text(1050, 287, "练习模式", 12.5, 400, INK)
    f.line([(700, 295), (645, 295), (645, 130)])
    f.text(637, 215, "改完简历重新投", 12.5, 400, INK, "end")

    f.box(1090, 420, 270, 100, "⑥ 模拟面试（图 B）", ["一轮专业面 · 5 个话题", "每个话题最多追问 1 次", "练习模式每题答完马上点评"])
    f.box(700, 420, 310, 100, "⑦ 面试报告", ["通过 / 没通过：完整总结 + 改进建议", "练习模式、没聊完：不下通过结论", "逐题回顾 · 和简历问题的关联"])
    f.box(40, 420, 330, 100, "我的投递", ["所有投递新的在前，回看初筛结果", "这次投递下的面试挂在卡片上", "没面完的接着面，面完的看报告"], dash=True)
    f.line([(1225, 340), (1225, 420)])
    f.line([(1090, 470), (1010, 470)])
    f.line([(370, 470), (700, 470)], dash=True)
    f.text(535, 462, "回看", 12.5, 400, INK)
    f.legend(40, 568, [("#fff", "用户操作的页面", None), (LLM_FILL, "后台自动运行（调用模型）", None),
                       ("#fff", "随时可以进入的列表页", "dash")])
    return f


# ═════════════════════════════ 图 3 图 A ═════════════════════════════
def fig_graph_a() -> Fig:
    f = Fig("图3-图A投递流水线", 1440, 790)
    f.group(24, 20, 1392, 176, "解析（不在图里）：上传简历时由后台任务触发，按顺序调用 parser/ 里的函数，最后一次落库")
    steps = [("抽取", ["PyMuPDF 按行取字", "找表格"], "extract", False),
             ("版面", ["分栏 · 表格 · 时间轴", "定下 full_text"], "layout", False),
             ("章节识别", ["词典 + 版面打分"], "section", False),
             ("基本信息", ["本地抽取，不外发"], "basics", False),
             ("章节兜底", ["认不出的标题", "交模型归类"], "section_llm", True),
             ("结构化", ["模型只回块编号", "日期本地归一化"], "structure", True),
             ("技能提及", ["词典扫技能"], "mentions", False),
             ("落库", ["同一事务写入", "出错也标失败"], None, False)]
    sw, sg = 146, (1352 - 8 * 146) / 7
    for i, (t, ls, code, llm) in enumerate(steps):
        x = 44 + i * (sw + sg)
        f.box(x, 56, sw, 120, t, ls, code, fill=LLM_FILL if llm else "#fff")
        if i:
            f.line([(x - sg, 116), (x, 116)])
    f.line([(720, 196), (720, 236)])
    f.text(730, 221, "解析完才开始（投递时还没解析完就先等）", 12, 400, INK2, "start")

    f.group(24, 236, 1392, 470, "图 A · 投递流水线（POST /apply 触发；每过一个节点推送一次进度）")
    f.circle(70, 460, "开始")
    cw, cg = 176, 28
    col = [150 + i * (cw + cg) for i in range(5)]
    f.group(130, 280, 1032, 160, "diagnose 子图：诊断简历本身", GROUP2_FILL)
    diag = [("规则扫描", ["7 条规则"], "rule_scan", False),
            ("送审计划", ["成本预检，选出", "要送审的单元"], "plan_review", False),
            ("逐条审阅 × N", ["Send：每条描述一个分支", "模型审阅 → 引用逐字校验", "对不上带原因重试 ≤ 2 次"], "review_unit", True),
            ("合并去重", ["同一维度、证据重叠", "超过一半的只留规则"], "merge_findings", False),
            ("五维打分", ["从 100 分往下扣", "按经历条数摊薄"], "score", False)]
    for i, (t, ls, code, llm) in enumerate(diag):
        if llm:  # 叠两层，表示分出了 N 个分支
            f.rect(col[i] + 8, 316 - 8, cw, 108, LLM_FILL)
            f.rect(col[i] + 4, 316 - 4, cw, 108, LLM_FILL)
        f.box(col[i], 316, cw, 108, t, ls, code, fill=LLM_FILL if llm else "#fff")
        if i:
            f.line([(col[i - 1] + cw, 370), (col[i], 370)])

    f.group(130, 470, 1032, 160, "match 子图：对照岗位要求", GROUP2_FILL)
    match = [(0, "规则先判", ["技能名本身、学历、年限", "只判十拿九稳的"], "rule_match", False),
             (2, "全文判断", ["其余要求连同简历全文", "一次交给模型", "依据须逐字引用简历"], "judge_fulltext", True),
             (4, "加权算分", ["按权重公式", "算匹配度"], "score_match", False)]
    for k, (c, t, ls, code, llm) in enumerate(match):
        f.box(col[c], 506, cw, 108, t, ls, code, fill=LLM_FILL if llm else "#fff")
        if k:
            f.line([(col[match[k - 1][0]] + cw, 560), (col[c], 560)])

    f.line([(87, 460), (110, 460), (110, 370), (col[0], 370)])
    f.line([(110, 460), (110, 560), (col[0], 560)])
    f.line([(col[4] + cw, 370), (1180, 370), (1180, 460), (1196, 460)])
    f.line([(col[4] + cw, 560), (1180, 560), (1180, 460)], arrow=False)
    f.box(1196, 420, 120, 80, "初筛", ["匹配度 ≥ 60"], "gate")
    f.line([(1316, 460), (1353, 460)])
    f.circle(1370, 460, "结束")
    f.text(130, 662, "· 两个子图并行、互不依赖，都完成才到初筛；每个子图也能单独调用（评测做消融时直接调）。", 12.5, 400, INK, "start")
    f.text(130, 686, "· 对照实验开关：诊断 rule_only / llm_only / hybrid，匹配 dict_only / llm_fulltext / hybrid，线上都用 hybrid。",
           12.5, 400, INK, "start")
    f.legend(40, 750, [("#fff", "纯函数（不调模型）", None),
                       (LLM_FILL, "调用模型（都经 llm/；模型引用的原文要过 locate_span 逐字核对）", None)])
    return f


# ═════════════════════════════ 图 4 图 B ═════════════════════════════
def fig_graph_b() -> Fig:
    f = Fig("图4-图B模拟面试", 1460, 620)
    f.circle(50, 300, "开始")
    nodes = [(90, 160, "定话题", ["模型定 5 个话题", "每个指向一条材料"], "plan_interview", "llm"),
             (290, 130, "取话题", ["下一个话题"], "pick_topic", "fn"),
             (460, 170, "查面经", ["只查用户贴的面经", "不长就整段给"], "retrieve_context", "fn"),
             (670, 150, "出题", ["模型流式输出"], "ask_question", "llm"),
             (860, 170, "等回答 ★", ["interrupt() 停住", "检查点存 SQLite"], "wait_answer", "wait"),
             (1070, 170, "评分", ["按 rubric 三项打分", "依据逐字引用回答"], "evaluate_answer", "llm"),
             (1280, 150, "决定下一步", ["看花费、追问次数"], "decide", "fn")]
    f.line([(67, 300), (90, 300)])
    for i, (x, w, t, ls, code, kind) in enumerate(nodes):
        f.box(x, 250, w, 100, t, ls, code, fill=LLM_FILL if kind == "llm" else "#fff", sw=2.8 if kind == "wait" else 1.4)
        if i:
            px, pw = nodes[i - 1][0], nodes[i - 1][1]
            f.line([(px + pw, 300), (x, 300)])

    f.box(560, 70, 200, 84, "出报告", ["分数纯函数聚合", "模型只写文字总结"], "final_report", fill=LLM_FILL)
    f.line([(760, 112), (803, 112)])
    f.circle(820, 112, "结束")
    f.line([(355, 250), (355, 112), (560, 112)])
    f.text(363, 190, "话题用完", 12.5, 400, INK, "start")
    f.line([(1355, 250), (1355, 40), (660, 40), (660, 70)])
    f.text(1000, 33, "finish：花费到上限", 12.5, 400, INK)
    f.line([(1330, 350), (1330, 400), (745, 400), (745, 350)])
    f.text(1040, 393, "followup：追问（每个话题最多 1 次，跳过的不追问）", 12.5, 400, INK)
    f.line([(1380, 350), (1380, 450), (355, 450), (355, 350)])
    f.text(860, 443, "next：换下一个话题", 12.5, 400, INK)
    f.line([(270, 220), (270, 372)], arrow=False, dash=True, color="#777")
    f.text(270, 210, "创建会话只跑到这里", 12, 400, INK2)

    notes = ["· 创建会话（POST /interviews）只跑完「定话题」就停；开始面试（POST /start）接着跑到第一题的「等回答」。",
             "· 每次提交回答：先落库，再从「等回答」原地继续；跳过的题记 0 分、不调模型。提前结束不经过图，按已答的题直接出报告。",
             "· 练习模式每题答完马上显示评分；正常模式答题时不显示，结束后看报告。两种模式后台都逐题评分（追问要用）。"]
    for i, s in enumerate(notes):
        f.text(40, 500 + i * 24, s, 12.5, 400, INK, "start")
    f.legend(40, 594, [("#fff", "纯函数", None), (LLM_FILL, "调用模型", None), ("#fff", "等人输入（interrupt）", "thick")])
    return f


# ═════════════════════════════ 图 5 E-R ═════════════════════════════
TABLES = {  # 名字: (x, y, 中文, [(列, 说明)])
    "users": (40, 60, "用户", [("id", "PK"), ("username", "唯一"), ("password_hash", ""), ("email", "唯一，可空")]),
    "resumes": (380, 60, "简历", [("id", "PK"), ("user_id", "FK"), ("file_hash", "同一文件去重"), ("parse_status", ""),
                                 ("full_text", "坐标系"), ("structure", "JSON"), ("is_deleted", "软删除")]),
    "parsed_blocks": (740, 30, "解析块", [("id", "PK"), ("resume_id", "FK"), ("block_index", "阅读顺序"),
                                         ("text", ""), ("char_start / end", "")]),
    "diagnoses": (740, 210, "诊断", [("id", "PK"), ("resume_id", "FK"), ("mode", ""), ("overall_score", ""),
                                    ("score_detail", "JSON")]),
    "findings": (1100, 210, "诊断问题", [("id", "PK"), ("diagnosis_id", "FK"), ("source", "rule / llm"),
                                       ("evidence_quote", "原文引用"), ("char_start / end", ""), ("verify_result", "")]),
    "jobs": (380, 560, "岗位", [("id", "PK"), ("user_id", "FK，模板为空"), ("title", ""), ("domain", "求职方向"),
                              ("requirements", "JSON"), ("is_deleted", "软删除")]),
    "match_reports": (740, 420, "投递（匹配报告）", [("id", "PK = 投递 id"), ("resume_id", "FK"), ("job_id", "FK"),
                                               ("diagnosis_id", "FK"), ("overall_match", ""), ("passed", "是否过线"),
                                               ("items", "JSON")]),
    "interview_sessions": (1100, 420, "面试", [("id", "PK"), ("user_id", "FK"), ("resume_id", "FK"), ("job_id", "FK"),
                                             ("match_report_id", "FK"), ("mode / status", ""), ("plan", "JSON"),
                                             ("report", "JSON")]),
    "interview_turns": (1100, 680, "问答", [("id", "PK"), ("session_id", "FK"), ("topic_idx / depth", ""),
                                          ("question", ""), ("answer", ""), ("evaluation", "JSON")]),
    "skills": (40, 560, "技能词典", [("id", "PK"), ("canonical_name", "唯一"), ("aliases", "JSON")]),
    "llm_calls": (40, 700, "模型调用审计", [("id", "PK"), ("scene", ""), ("model_name", ""), ("token_input / output", ""),
                                         ("cost", ""), ("cache_hit", "")]),
}
TW, TH_HEAD, TH_ROW = 250, 32, 20


def fig_er() -> Fig:
    f = Fig("图5-数据库E-R", 1400, 910)
    for name, (x, y, cn, cols) in TABLES.items():
        h = TH_HEAD + len(cols) * TH_ROW + 10
        f.rect(x, y, TW, h, "#fff", r=6)
        f.els.append(f'<rect x="{x}" y="{y}" width="{TW}" height="{TH_HEAD}" rx="6" fill="{HEAD_FILL}" stroke="{LINE}" stroke-width="1.4"/>')
        f.text(x + 12, y + 21, name, 13, 700, INK, "start", mono=True)
        f.text(x + TW - 12, y + 21, cn, 12.5, 700, INK, "end")
        for i, (c, note) in enumerate(cols):
            yy = y + TH_HEAD + 18 + i * TH_ROW
            f.text(x + 12, yy, c, 12, 700 if note.startswith(("PK", "FK")) else 400, INK, "start", mono=True)
            if note:
                f.text(x + TW - 12, yy, note, 11.5, 400, INK2, "end")

    def rel(pts, a="1", b="N"):
        """父表 → 子表；两端标 1 / N"""
        f.line(pts, arrow=False)
        for (x, y), (nx, ny), s in ((pts[0], pts[1], a), (pts[-1], pts[-2], b)):
            if y == ny:   # 端点所在的一段是横的
                f.text(x + (10 if nx > x else -10), y - 6, s, 12, 700, INK)
            else:
                f.text(x + 9, y + (16 if ny > y else -8), s, 12, 700, INK)

    rel([(290, 120), (380, 120)])                                                   # users → resumes
    rel([(290, 150), (335, 150), (335, 640), (380, 640)])                           # users → jobs
    rel([(290, 170), (320, 170), (320, 880), (1085, 880), (1085, 605), (1100, 605)])  # users → interview_sessions
    rel([(630, 100), (740, 100)])                                                   # resumes → parsed_blocks
    rel([(630, 228), (740, 228)])                                                   # resumes → diagnoses
    rel([(560, 242), (560, 470), (740, 470)])                                       # resumes → match_reports
    rel([(600, 60), (600, 14), (1375, 14), (1375, 520), (1350, 520)])               # resumes → interview_sessions
    rel([(990, 290), (1100, 290)])                                                  # diagnoses → findings
    rel([(865, 352), (865, 420)], "1", "0..1")                                      # diagnoses → match_reports
    rel([(630, 590), (740, 590)])                                                   # jobs → match_reports
    rel([(630, 690), (1040, 690), (1040, 560), (1100, 560)])                        # jobs → interview_sessions
    rel([(990, 500), (1100, 500)])                                                  # match_reports → interview_sessions
    rel([(1225, 622), (1225, 680)])                                                 # interview_sessions → interview_turns
    f.text(300, 900, "PK 主键 · FK 外键 · 连线两端 1 / N 表示一对多；skills、llm_calls 不建外键；简历和岗位在业务上是软删除",
           12, 400, INK2, "start")
    return f


# ═════════════════════════════ 柱状图 ═════════════════════════════
def bars(f: Fig, x0, y0, w, h, groups, series, ymax=100, step=20, ylabel="", bw_max=30, hline=None):
    """groups: 每组下面的标签（几行）；series: [(名字, 填充, 数值, 柱顶标签或 None)]"""
    for v in range(0, ymax + 1, step):
        y = y0 + h - v / ymax * h
        f.line([(x0, y), (x0 + w, y)], arrow=False, color="#d0d0d0" if v else LINE, sw=1 if v else 1.4)
        f.text(x0 - 8, y + 4, str(v), 12, 400, INK2, "end")
    f.text(x0 - 48, y0 + h / 2, ylabel, 13, 400, INK, rotate=-90)
    if hline is not None:
        y = y0 + h - hline[0] / ymax * h
        f.line([(x0, y), (x0 + w, y)], arrow=False, dash=True, color=INK)
        f.text(x0 + w - 4, y - 6, hline[1], 12, 400, INK, "end")
    gw = w / len(groups)
    bw = min(bw_max, gw * 0.78 / len(series))
    for gi, lab in enumerate(groups):
        cx = x0 + gw * (gi + 0.5)
        for si, (_, fill, vals, labels) in enumerate(series):
            v = vals[gi]
            bx = cx - bw * len(series) / 2 + si * bw
            bh = v / ymax * h
            if bh:
                f.rect(bx + 1, y0 + h - bh, bw - 2, bh, fill, r=0, sw=1)
            s = labels[gi] if labels else (f"{v:.0f}" if v in (0, 100) else f"{v:.1f}")
            f.text(bx + bw / 2, y0 + h - bh - 5, s, 11, 400, INK)
        for li, s in enumerate(lab):
            f.text(cx, y0 + h + 20 + li * 16, s, 12.5, 400, INK)


def chart_legend(f: Fig, x, y, series):
    f.legend(x, y, [(fill, name, None) for name, fill, *_ in series], gap=28)


def fig_layout_eval() -> Fig:
    f = Fig("图6-版面解析准确率", 1200, 540)
    series = [("PyMuPDF 自带排序（sort=True）", SERIES[0], [100, 34.9, 41.8, 100, 100, 100, 77.7], None),
              ("最初的规则（无表格识别、时间轴日期列）", SERIES[1], [100, 100, 100, 77.4, 83.0, 77.5, 89.8], None),
              ("现在的规则", SERIES[2], [100, 100, 100, 100, 100, 89.3, 98.2], None)]
    chart_legend(f, 100, 34, series)
    bars(f, 100, 70, 1060, 360, [["单栏"], ["两栏"], ["侧边栏"], ["表格型"], ["时间轴"], ["无边框表格型"], ["总体"]],
         series, ylabel="相邻行对顺序准确率（%）")
    f.text(100, 510, "合成简历 120 份（20 份虚构内容 × 6 种版式），标准答案是生成时的绘制顺序。", 12.5, 400, INK2, "start")
    return f


def fig_match_eval() -> Fig:
    f = Fig("图7-匹配消融", 1200, 624)
    series = [("dict_only（只用规则）", SERIES[0], [100, 100, 100, 0, 0, 100, 75.0], None),
              ("llm_fulltext（只用模型）", SERIES[1], [100, 85.0, 100, 100, 100, 100, 98.1], None),
              ("hybrid（规则先判，其余交给模型，再复核技能栏）", SERIES[2], [100, 100, 100, 100, 100, 100, 100], None)]
    chart_legend(f, 100, 34, series)
    bars(f, 100, 70, 1060, 360,
         [["项目里用过的技能", "（满足）"], ["只写在技能栏", "（部分满足）"], ["简历里没有的技能", "（不满足）"],
          ["A 或 B 有其一", "（满足）"], ["描述里有依据", "（满足）"], ["学历 / 年限 / 英语", "（满足或不满足）"], ["总体"]],
         series, ylabel="与标准答案的一致率（%）")
    notes = ["20 份简历 × 8 条要求 = 160 条，满足与否在造数据时就定好；dict_only、llm_fulltext 重复 3 次；hybrid 是加了技能栏复核之后的（实跑 1 次 + 离线重算 3 次都是 100%），",
             "加复核之前 hybrid 总体 97.7±0.4%、只写在技能栏 81.7±2.9%（模型看到「专业技能中列出了 X」就判满足）。",
             "每份交给模型的条数 / 花费 / 用时：dict_only 0 / 0 元 / 毫秒级；llm_fulltext 8 / ¥0.0092 / 2.5 s；hybrid 5 / ¥0.0067 / 1.9 s。"]
    for i, s in enumerate(notes):
        f.text(100, 540 + i * 24, s, 12.5, 400, INK2, "start")
    return f


def fig_diagnose_eval() -> Fig:
    f = Fig("图8-诊断消融", 1200, 580)
    series = [("rule_only（只用规则）", SERIES[0], [100, 100, 100, 100, 0, 0, 0], None),
              ("llm_only（只用模型）", SERIES[1], [95, 53, 0, 0, 100, 100, 100], None),
              ("hybrid（规则 + 模型）", SERIES[2], [100, 100, 100, 100, 100, 100, 100], None)]
    chart_legend(f, 100, 34, series)
    x0, w = 100, 1060
    bars(f, x0, 70, w, 360, [["删掉量化数字"], ["「协助」弱动词"], ["没用过的技能"], ["7 个月空窗"], ["夸大"], ["前后矛盾"], ["职责不清"]],
         series, ylabel="检出率（%，位置命中）")
    gw = w / 7
    for a, b, s in ((0, 4, "规则类缺陷"), (4, 7, "语义类缺陷")):
        xa, xb = x0 + gw * a + 12, x0 + gw * b - 12
        f.line([(xa, 466), (xa, 474), (xb, 474), (xb, 466)], arrow=False)
        f.text((xa + xb) / 2, 494, s, 13, 700, INK)
    notes = ["降质集 60 份，每种缺陷 20 处；每种模式跑 3 次，规则部分 3 次完全一样，llm_only 弱动词 3 次在 50–55 之间（图中为均值）。",
             "模型给出的引用 3 次共 979 条，全部能在原文逐字找到（拦截率 0%）。"]
    for i, s in enumerate(notes):
        f.text(100, 530 + i * 24, s, 12.5, 400, INK2, "start")
    return f


def fig_interview_eval() -> Fig:
    f = Fig("图9-面试评分区分度", 1000, 560)
    series = [("计算机方向（技术面）", SERIES[0], [86.1, 39.2, 37.8], None),
              ("运营方向（运营面）", SERIES[1], [84.3, 34.4, 37.9], None)]
    chart_legend(f, 100, 34, series)
    bars(f, 100, 70, 860, 360, [["具体到位"], ["空泛"], ["答错"]], series, ylabel="单题得分（0–100，3 次平均）",
         bw_max=70, hline=(60, "整场面试的通过线 60（参考）"))
    notes = ["每个方向 12 道题 × 三档回答（档位在写回答时就定好），每条回答打分 3 次。",
             "具体档最低 80 / 73 分，另两档最高都是 53 分，没有交叉；3 次都是「具体 > 空泛」「具体 > 答错」12 / 12。"]
    for i, s in enumerate(notes):
        f.text(100, 500 + i * 24, s, 12.5, 400, INK2, "start")
    return f


def main() -> None:
    browser = find_browser()
    if not browser:
        print("没找到 Chrome / Edge，只出 SVG")
    for make in (fig_architecture, fig_product_flow, fig_graph_a, fig_graph_b, fig_er,
                 fig_layout_eval, fig_match_eval, fig_diagnose_eval, fig_interview_eval):
        make().save(browser)


if __name__ == "__main__":
    main()
