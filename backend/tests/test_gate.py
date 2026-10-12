"""进门的闸门（app/gate.py）：同时处理中的请求有上限，多的排队；响应一开始往回发就算出门。"""
import asyncio

import pytest

from app.gate import RequestGate

HTTP = {"type": "http"}


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


async def _respond(send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def test_only_so_many_requests_are_inside_at_once_and_the_rest_wait_in_order():
    inside, peak, entered, answered = 0, 0, [], []

    async def app(scope, receive, send):
        nonlocal inside, peak
        inside += 1
        peak = max(peak, inside)
        entered.append(scope["n"])
        await asyncio.sleep(0.01)           # 还在处理：这时候别的请求只能等
        inside -= 1
        await _respond(send)

    async def main():
        gate = RequestGate(app, limit=2)

        async def send(message):
            if message["type"] == "http.response.start":
                answered.append(message["status"])

        await asyncio.gather(*(gate({**HTTP, "n": n}, _receive, send) for n in range(7)))

    asyncio.run(main())
    assert peak == 2
    assert entered == list(range(7))        # 先来的先进
    assert answered == [200] * 7            # 排队的只是晚一点，一个都不丢


def test_a_request_leaves_the_gate_as_soon_as_its_response_starts():
    """进度流、后台分析都发生在响应开始之后，可能持续几分钟：不能一直占着名额，否则十几个人看着进度条就把门堵死了。"""
    async def main():
        still_streaming, second_done = asyncio.Event(), asyncio.Event()

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            if scope["n"] == 1:
                await still_streaming.wait()            # 第一个请求：响应开了头，后面还要发很久
            else:
                second_done.set()
            await send({"type": "http.response.body", "body": b""})

        async def send(message):
            pass

        gate = RequestGate(app, limit=1)
        first = asyncio.create_task(gate({**HTTP, "n": 1}, _receive, send))
        await asyncio.wait_for(gate({**HTTP, "n": 2}, _receive, send), timeout=1)    # 第一个还没发完，第二个照样进得来
        assert second_done.is_set() and not first.done()
        still_streaming.set()
        await first

    asyncio.run(main())


def test_a_request_that_fails_before_responding_gives_its_slot_back():
    async def main():
        async def app(scope, receive, send):
            if scope["n"] == 1:
                raise RuntimeError("boom")
            await _respond(send)

        async def send(message):
            pass

        gate = RequestGate(app, limit=1)
        with pytest.raises(RuntimeError):
            await gate({**HTTP, "n": 1}, _receive, send)
        await asyncio.wait_for(gate({**HTTP, "n": 2}, _receive, send), timeout=1)

    asyncio.run(main())


def test_startup_and_shutdown_messages_do_not_go_through_the_gate():
    called = []

    async def app(scope, receive, send):
        called.append(scope["type"])

    asyncio.run(RequestGate(app, limit=0)({"type": "lifespan"}, _receive, None))      # 名额是 0 也不会被挡住
    assert called == ["lifespan"]
