"""汇总全部路由。新增一个模块的接口：在这里 include 一行。"""
from fastapi import APIRouter

from app.api import admin, advice, apply, auth, diagnose, domain, interview, job, match, resume, system, task

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(resume.router)
api_router.include_router(diagnose.router)
api_router.include_router(domain.router)
api_router.include_router(job.router)
api_router.include_router(match.router)
api_router.include_router(apply.router)
api_router.include_router(task.router)
api_router.include_router(advice.router)
api_router.include_router(interview.router)
api_router.include_router(admin.router)
