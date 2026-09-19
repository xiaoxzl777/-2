# 智能求职辅助系统：简历诊断与模拟面试

本科毕业设计。求职者上传简历 → 版面感知解析 → 规则⊕LLM 混合诊断（证据可溯源）→ 粘贴 JD 做匹配与模拟初筛 → 技术面 / HR 面模拟面试 → 面试报告与改写建议。

设计文档在 [docs/](docs/)，是唯一事实来源：改设计先改文档，再改代码。

| 文档 | 内容 |
|---|---|
| [00-overview](docs/00-overview.md) | 产品主线、系统不变量、技术栈 |
| [01-requirements](docs/01-requirements.md) | 功能 / 非功能需求、诊断规则清单 |
| [02-database](docs/02-database.md) | 11 张表建表 SQL、JSON 字段结构、Chroma collection |
| [03-api](docs/03-api.md) | 24 个接口、错误码、SSE 契约、示例 |
| [04-design](docs/04-design.md) | AI 模块、核心算法、后端设计 |
| [05-evaluation-and-plan](docs/05-evaluation-and-plan.md) | 里程碑、评估方案、验证方式 |

## 技术栈

后端 Python 3.11+ / FastAPI / SQLAlchemy 2.0 / LangGraph + LangChain · 前端 React 18 + TS + Vite + Tailwind + shadcn/ui · 存储 MySQL 8.0 + Chroma + Redis · 模型 DeepSeek（对话）+ 硅基流动 bge-m3（向量）· 部署 Nginx + Docker Compose

## 开发环境（本地跑 API 与前端，MySQL/Redis 用本机或容器）

```powershell
# 1. 环境变量（唯一需要手填的地方：MySQL 密码、API key；.env 不进仓库）
Copy-Item .env.example .env

# 2. Redis：启动本机 Redis；本机没装就用容器
docker compose up -d redis

# 3. 后端（首次启动会自动建库建表，无需手动执行 SQL）
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload      # http://localhost:8000/docs
                                   # 自检：http://localhost:8000/api/v1/health

# 4. 前端（M2 起）
cd ..\frontend
npm install
npm run dev                        # Vite 代理 /api 到 8000
```

## 部署 / 答辩演示

```powershell
docker compose up -d --build       # mysql + redis + backend + nginx，http://localhost
```

## 目录

```
backend/app/     api · services · parser · diagnose · matching · interview · retrieval · graphs · llm · cache
backend/scripts/ init_db · seed · build_ontology · gen_eval_set · run_eval
backend/tests/
data/            skills_seed.csv · jd.jsonl · cases.jsonl · resumes/ · uploads/ · chroma/ · eval_runs/
docs/            设计文档
frontend/        React 前端（M2 起）
nginx/           反向代理配置
```
