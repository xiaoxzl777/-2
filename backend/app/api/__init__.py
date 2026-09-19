"""汇总全部路由。新增一个模块的接口：在这里 include 一行。"""
from fastapi import APIRouter

from app.api import auth, system

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system.router)
api_router.include_router(auth.router)
