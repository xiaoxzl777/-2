"""SSE（text/event-stream）的公共部分：进度流（task.py）、具体建议（advice.py）、模拟面试（interview.py）共用。"""
from __future__ import annotations

import json
from collections.abc import Iterable

from fastapi.responses import StreamingResponse


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_response(chunks: Iterable[str]) -> StreamingResponse:
    """chunks：拼好的 SSE 文本（sse_event 的结果，或 ": ping" 这样的心跳注释行）。"""
    return StreamingResponse(chunks, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})  # 后者让 Nginx 不要缓冲
