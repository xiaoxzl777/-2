# CLAUDE.md —— 给接手的 AI 看的项目交接

> 最后更新：2026-09-27。本文件记录**当前进度、用户的工作习惯、已定下的决定和下一步**。
> 设计细节以 `docs/` 为准（README 有索引），这里不重复。

## 1. 项目一句话

本科毕设「智能求职辅助系统」：上传简历 → 解析 → 诊断（规则 + LLM，证据可溯源）→ 粘贴 JD 做匹配与模拟初筛 → 模拟面试。
后端 FastAPI + LangGraph + MySQL + Redis + Chroma；前端 React 18 + TS + Vite + Tailwind v4 + Zustand。

先读：`README.md` → `docs/06-workflows.md`（产品流程与两张图，最新设计）→ `docs/07-代码导读.md`（后端逐目录说明）。

## 2. 用户的工作习惯（必须遵守）

- **全程用中文回复。**
- **先商量、用户明确同意后再写代码。** 新功能先给方案或效果预览，拿到"可以 / 同意"再动手。
- **有不确定就问，一次只问一个问题。**
- **只在用户说"提交"时才 git commit。** 提交信息用中文，风格见 `git log`。
- 做 UI 时先出一个**独立 HTML 效果预览**（放桌面 `C:\Users\Administrator\Desktop\`），用户看满意了再落到 `frontend/`。
- 用户换过一次账号（2026-09-27），之前的对话记录不在了，以本文件为准。

## 3. 当前进度

### 后端（已完成，272 个测试全过）
- 解析、诊断、JD 解析、匹配、图 A（诊断 ∥ 匹配 → 初筛）、`POST /apply` + SSE 进度，都已实现。
- 26 个接口已实现 18 个，未实现的在 `docs/03-api.md` 标了〔未实现〕：改写、模拟面试（图 B）、`PATCH /resumes/{id}/structure`、`/system/info`。
- 匹配**不用 RAG**（已实测，理由见 `docs/06-workflows.md` 6.2）；检索代码（`retrieval/`、`llm/embedding.py`）留给模拟面试。

### 前端（`frontend/`）
- 已完成并提交：
  - 首页 `/`：可玩的演示卡，用固定示例数据。
  - 登录 / 注册弹窗：从点击位置圆形展开，背景有漂浮的产品碎片。
  - 登录后的占位页 `/app`。
- 登录状态：令牌存 localStorage，刷新时用 `/auth/me` 恢复；任意接口 401 自动退出；未登录访问 `/app` 会回到 `/?login=1` 并自动弹出登录框。

### 正在做：工作台（投递三步）
- 效果预览：`docs/design/工作台预览.html`（桌面也有一份），**用户还没确认满意**，下一步先问用户这一版行不行。
- 设计：一步一屏，版式同首页首屏（左大标题 + 手绘下划线，右操作卡 + 漂浮小卡）：
  ① 你想投哪个岗位（粘贴 JD / 我的岗位 / 模板）→ ② 用哪份简历去投（上传 / 选已有）→ ③ 准备好了，投吧（流程卡实时进度）→ 结果（匹配度圆环 + 四维分 + 差距 / 简历问题两个标签页）。
- 要接的后端接口：`POST/GET /jobs`、`POST/GET /resumes`、`POST /apply`、`GET /tasks/apply/{id}/stream`（SSE）、`GET /apply/{id}`。
- 用户的原话："后台感就留在管理端，用户看的就不用这样了"。用户侧页面一律用首页风格，后台风格只给管理端用。

## 4. 已定下的决定

| 事项 | 决定 |
|---|---|
| 前端视觉 | 暖色奶油底 `#f6f0e6`、墨色 `#221d17`、强调橙 `#d9542b`。交互：鼠标跟随光晕、磁吸按钮、卡片倾斜、进场与滚动动画。样稿：`docs/design/首页预览.html` |
| 被否掉的风格 | iOS 毛玻璃 + 彩色光斑（"AI 味太重"）；iOS 系统设置风（"更难看"）；左右分栏 + 侧边摘要的后台风（工作台第一版） |
| 文档与代码冲突 | **以代码为准**，改文档。文档之间冲突时以 `06-workflows`（v4）为准 |
| 登录后去哪 | 暂时进占位页 `/app`，工作台做好后替换 |
| 首页演示 | 保留，用固定示例数据，卡片上标"示例数据" |
| 登录规则 | 账号密码对就能进，不加验证码或邮箱验证 |

## 5. 本地运行与测试

```powershell
# 后端（需要本机 MySQL + Redis 已启动，.env 已配置）
cd backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
.\.venv\Scripts\python.exe -m pytest -q            # 272 个用例，不联网

# 前端
cd frontend; npm run dev                           # http://localhost:5173，/api 转发到 8000
npm run build                                      # tsc 类型检查 + 构建
```

- **测试账号**：`user` / `88888888`（本机库里，用户指定的）。自动测试若注册了临时账号，用完要删掉。
- 浏览器自动测试：用 `playwright-core` 加本机 Chrome（`chromium.launch({ channel: 'chrome' })`），装在临时目录，不要装进项目。

## 6. 踩过的坑

- **本机有 HTTP 代理**：`curl localhost` 会返回 Forbidden，要加 `--noproxy '*'`。
- **Tailwind v4 自带 `collapse` 工具类**（`visibility: collapse`），自定义类名别用 `collapse`（已踩过，改成了 `.expand`）。同理避开 `hidden`、`block`、`grid` 等 Tailwind 类名。
- 前端组件样式集中在 `frontend/src/index.css`（手写 CSS + `@theme` 色板），没有逐个用 Tailwind 工具类，新页面沿用这种写法。
- 部分文件是 CRLF 换行，脚本批量改文件时注意保留原换行。
- MySQL 默认 REPEATABLE READ：后台任务轮询状态前要先 `commit()` 再 `refresh()`（见 `apply_service._wait_until_parsed`）。

## 7. 已知缺口（还没做，也还没和用户商量）

- DOCX 没有做字数上限检查（`MAX_DOCX_CHARS` 没用上），42201 对 DOCX 不会触发。
- 岗位模板：数据库里 0 条，`seed.sql` 只有技能词典。工作台的「模板」页签需要补 5–8 份模板 JD。
- 模拟面试怎么检索材料：`06-workflows` 里同时写了 `retrieve_context` 节点和 `search_materials` 工具两种说法，做 M7 之前要和用户定下来。
- 文档里的 shadcn/ui、TanStack Query 还没引入，需要时再加。
- 部署：`docker compose` 的 nginx 挂载 `frontend/dist`，部署前要先 `npm run build`。

## 8. 下一步

1. 问用户：工作台预览（`docs/design/工作台预览.html`）这一版满不满意，要改什么。
2. 用户同意后，在 `frontend/` 里实现工作台，接上真实接口。按之前商量的顺序：先做投递三步和进度，结果页先做分数和差距列表，原文高亮下一轮再做。
3. 之后：结果页的原文高亮（`GET /resumes/{id}/blocks` + 诊断 / 匹配的 char 区间）→ 岗位模板数据 → 改写 → 模拟面试（图 B）。
