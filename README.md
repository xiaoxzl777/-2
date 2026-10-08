# 智能求职辅助系统：简历诊断与模拟面试

本科毕业设计。求职者先选求职方向（计算机 / 运营 / 财会金融）、定目标岗位（粘贴 JD 或选内置模板）→ 上传简历（版面感知解析）→ 一键投递：规则⊕LLM 混合诊断（证据可溯源）与岗位匹配并行，给出模拟初筛结果 → 按方向模拟面试（技术面 / 运营面 / 专业面）→ 面试报告。结果页上点开一条问题，可以现场生成具体的修改建议；整份诊断还能预览成报告、下载成 PDF，对照着改简历。

设计文档在 [docs/](docs/)。文档与代码冲突时以代码为准（回头改文档）；文档之间冲突时以 [06-workflows](docs/06-workflows.md) 为准。

| 文档 | 内容 |
|---|---|
| [00-overview](docs/00-overview.md) | 概览：产品主线、系统不变量、技术栈 |
| [01-requirements](docs/01-requirements.md) | 需求分析：功能 / 非功能需求、诊断规则清单 |
| [02-database](docs/02-database.md) | 数据库设计：每张表的用途与要点、外键、JSON 字段结构、预留字段、Chroma collection（完整建表语句以 `backend/sql/schema.sql` 为准） |
| [03-api](docs/03-api.md) | 接口设计：接口清单（标了哪些未实现）、错误码、SSE 契约、示例 |
| [04-design](docs/04-design.md) | AI 模块、核心算法与后端设计 |
| [05-evaluation-and-plan](docs/05-evaluation-and-plan.md) | 评测与计划：评测集、实验结果、验证方式、里程碑完成情况、不做与未来工作 |
| [06-workflows](docs/06-workflows.md) | 产品流程（JD 优先）、两张 LangGraph 图；与 04 冲突时以此为准 |
| [07-代码导读](docs/07-代码导读.md) | 后端各目录、各文件干什么，建议的阅读顺序 |
| [08-实现思路与代码讲解](docs/08-实现思路与代码讲解.md) | 后端每件事为什么这么做、关键代码、踩过的坑、答辩问题速查 |
| [design/](docs/design/) | 前端样稿（独立 HTML，浏览器直接打开）；`archive/` 里是被取代或被否掉的 |
| [figures/](docs/figures/) | 论文用图 9 张（架构、产品流程、图 A、图 B、E-R、四张评测图），各一份 SVG + PNG；`python docs/figures/make_figures.py` 重新生成（只用 Python 自带库，PNG 用本机 Chrome / Edge 截） |

## 技术栈

后端 Python 3.13 / FastAPI / SQLAlchemy 2.0 / LangGraph + LangChain · 前端 React 18 + TS + Vite + Tailwind v4 + Zustand · 存储 MySQL 8.0 + Chroma + Redis · 模型 DeepSeek（对话）+ 硅基流动 bge-m3（向量）· 部署 Nginx + Docker Compose

## 开发环境（本地跑 API 与前端，MySQL/Redis 用本机或容器）

```powershell
# 1. 环境变量（唯一需要手填的地方：MySQL 密码、API key；.env 不进仓库）
Copy-Item .env.example .env

# 2. Redis：启动本机 Redis；本机没装就起一个容器（部署用的 compose 不对外开 6379，开发时用不了）
docker run -d --name redis -p 6379:6379 redis:7-alpine

# 3. 建库建表 + 种子数据：在 MySQL 客户端中依次执行
#      backend\sql\schema.sql   （全新库执行一次）
#      backend\sql\seed.sql     （技能词典 + 岗位模板，可重复执行）
#    或命令行：cmd /c "mysql -uroot -p < backend\sql\schema.sql"

# 4. 后端（Python 3.13）
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.lock   # 锁定版本，与开发机完全一致（Windows / Python 3.13）
                                   # 其他 Python 版本可改用 requirements.txt，不保证能跑
uvicorn app.main:app --reload      # http://localhost:8000/docs
                                   # 自检：http://localhost:8000/api/v1/health

# 5. 测试（在 backend 下）：约 370 个用例、约 20 秒；模型、向量库、Redis 全部打桩，数据库用内存 SQLite，不联网
.\.venv\Scripts\python.exe -m pytest -q

# 6. 前端（另开一个终端）
cd ..\frontend
npm install
npm run dev                        # http://localhost:5173，/api 由 Vite 转发到 8000
```

## 部署 / 答辩演示（本机 Docker）

前提：装好并打开 Docker Desktop；项目根目录有 `.env`（同上第 1 步，至少填 `MYSQL_ROOT_PASSWORD`、`DEEPSEEK_API_KEY`、`SILICONFLOW_API_KEY`；
给别人用之前把 `JWT_SECRET` 改成随机长字符串）。

```powershell
docker compose up -d --build       # 第一次要构建镜像，几分钟；之后几秒
# 浏览器打开 http://localhost，注册一个账号就能用（首次启动自动建库，导入岗位模板和技能词典）

docker compose ps                  # 看几个容器的状态
docker compose logs -f backend     # 看后端日志
docker compose down                # 停掉，数据保留
docker compose down -v             # 停掉并清空所有数据，下次启动重新建库
```

- 四个容器：mysql、redis、backend、nginx（前端打包好放在 nginx 里，`/api` 转发给后端）。对外只开 80 端口，不占本机的 3306 / 6379，和开发环境可以同时开着。
- 数据在 Docker 数据卷里（`mysql_data`、`redis_data`、`backend_data`），和开发用的 `data/` 分开。
- Docker Desktop 开着时，电脑重启后容器会自己起来；后端偶尔比 MySQL 先起、连不上就退出，Docker 会接着重启它，等十几秒就好。
- 改了代码：`docker compose up -d --build`。改了 `schema.sql` / `seed.sql`：只对空数据卷生效，已有的库手动执行，或 `down -v` 重来。

## 目录

```
backend/             后端：app/（源码）、tests/、scripts/（生成种子数据、造评测集、跑评测）、sql/（建表与种子数据，脚本生成）、Dockerfile
frontend/            前端：首页、工作台（选方向 → 选岗位 → 选简历 → 投递）、我的投递、初筛结果、模拟面试（准备 / 面试 / 报告）；Dockerfile 打包后放进 Nginx
data/                进仓库的只有技能词典（skills_seed.csv）和岗位模板（job_templates/ 下 cs/、ops/ 的原文 + job_templates.json）；
                     其余（上传的简历、向量库、面试检查点、简历样本、评测集、评测结果）是运行时或脚本生成的，不进仓库
docs/                设计文档与前端样稿（见上表）
nginx/               Nginx 配置：托管前端页面，把 /api 转发给后端
docker-compose.yml   部署用的四个容器（mysql、redis、backend、nginx）
.env.example         环境变量模板，复制成 .env 后填写
```

后端逐目录、逐文件的说明（含 `scripts/` 各脚本和 `data/` 各子目录）见 [07-代码导读](docs/07-代码导读.md)。
