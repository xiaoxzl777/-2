"""进门的闸门：同时处理中的请求不超过 MAX_ACTIVE 个，多出来的在门口排队（压测时加的，经过见 docs/08 第 14 章）。

为什么要有：一个请求不是从头到尾占着一个线程。依赖、接口函数、返回值校验是分几次放进线程池跑的，每两步之间都要
重新等空闲线程，等的时候手里还占着数据库连接。人一多，线程全在等连接、占着连接的请求全在等线程，互相等到 30 秒
超时，整站卡住。闸门把「占着连接、又在等线程」的请求限制在 MAX_ACTIVE 个以内，连接池比它大（database.py），
总有空的连接；多出来的请求等在事件循环里，不占线程也不占连接——人再多也只是排队变慢，不会卡死。

响应一开始往回发就算出门：进度流、后台分析都在这之后，不占名额（它们用的数据库会话在返回前就关了）。
"""
from __future__ import annotations

import asyncio

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_ACTIVE = 40     # 和线程池一样大（AnyIO 默认 40 个线程）：再多放进来，也只是在里面等线程


class RequestGate:
    """ASGI 中间件。排队按先来后到（asyncio.Semaphore 是公平的）。"""

    def __init__(self, app: ASGIApp, limit: int = MAX_ACTIVE):
        self.app = app
        self.slots = asyncio.Semaphore(limit)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        await self.slots.acquire()
        inside = True

        def leave() -> None:
            nonlocal inside
            if inside:
                inside = False
                self.slots.release()

        async def send_and_leave(message: Message) -> None:
            if message["type"] == "http.response.start":
                leave()
            await send(message)

        try:
            await self.app(scope, receive, send_and_leave)
        finally:
            leave()         # 没发出响应就出错、或者客户端先断开了：名额照样要还
