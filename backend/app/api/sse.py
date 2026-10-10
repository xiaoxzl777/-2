"""SSE（text/event-stream）的公共部分：进度流（task.py）、具体建议（advice.py）、模拟面试（interview.py）共用。

两件容易忽略的事（10-10 审查时发现的）：
· 请求自己的数据库会话要在返回流式响应**之前**关掉（各接口里的 db.close()）：yield 依赖的收尾要等流发完才跑，
  不关的话这个连接整个流期间都被占着，进度流最长能开 10 分钟，十几个人同时看「分析中」就能把连接池占满。
· 客户端断开时，生成器的收尾要放到线程里做（下面的 _in_threads）：面试出题到一半页面刷新，关掉生成器要等图里的出题节点
  把模型的流读完；直接交给 Starlette 的话，这个同步生成器是在事件循环线程里被回收的，那几秒里所有请求都没人理。
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable, Iterator

import anyio
from fastapi.responses import StreamingResponse

_DONE = object()


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_response(chunks: Iterable[str]) -> StreamingResponse:
    """chunks：拼好的 SSE 文本（sse_event 的结果，或 ": ping" 这样的心跳注释行）。"""
    return StreamingResponse(_in_threads(iter(chunks)), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})  # 后者让 Nginx 不要缓冲


async def _in_threads(chunks: Iterator[str]) -> AsyncIterator[str]:
    """同步的生成器一段段放到线程里取；流提前结束（客户端断开）时，它的收尾也放到线程里做，做完才算完。"""
    try:
        while (chunk := await anyio.to_thread.run_sync(next, chunks, _DONE)) is not _DONE:
            yield chunk
    finally:
        close = getattr(chunks, "close", None)      # 列表的迭代器没有 close
        if close is not None:
            with anyio.CancelScope(shield=True):    # 断开时这个任务正在被取消：收尾不能跟着被取消
                await anyio.to_thread.run_sync(close)
