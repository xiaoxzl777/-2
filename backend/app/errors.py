"""统一错误：业务代码只抛 ApiError，由这里转成约定的响应格式 {code, message, data}。

错误码前三位就是 HTTP 状态码（40101 → 401，50003 → 500），见 docs/03-api.md 3.1。
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("app")

BAD_REQUEST = 40001
UNAUTHORIZED = 40101
FORBIDDEN = 40301
NOT_FOUND = 40401
CONFLICT = 40901
FILE_TOO_LARGE = 41301
UNSUPPORTED_FILE = 41501
FILE_TOO_LONG = 42201
TOO_MANY_REQUESTS = 42901
INTERNAL = 50001
LLM_FAILED = 50002
PARSE_FAILED = 50003


class ApiError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def http_status(self) -> int:
        return self.code // 100


def _body(code: int, message: str) -> dict:
    return {"code": code, "message": message, "data": None}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first["loc"] if p != "body")
        return JSONResponse(_body(BAD_REQUEST, f"参数错误：{field} {first['msg']}"), status_code=400)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理的异常", exc_info=exc)
        return JSONResponse(_body(INTERNAL, "服务器内部错误"), status_code=500)
