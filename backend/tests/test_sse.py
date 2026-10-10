"""SSE 响应：客户端断开时，生成器的收尾不能卡住整个服务。"""
import asyncio
import gc
import time

from app.api.sse import sse_event, sse_response


def test_event_format():
    assert sse_event("done", {"text": "好"}) == 'event: done\ndata: {"text": "好"}\n\n'


def test_closing_a_stream_does_not_block_the_event_loop():
    """面试出题到一半页面刷新：关掉生成器要等图里的出题节点把模型的流读完（几秒，模型卡住时更久）。
    这段等待必须在线程里，事件循环得照常转，不然这几秒里所有请求都没人理。"""
    closed = []

    def slow_to_close():
        try:
            yield "a"
            yield "b"
        finally:
            time.sleep(0.4)                 # 收尾很慢
            closed.append(True)

    async def main() -> int:
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        task = asyncio.create_task(ticker())
        body = sse_response(slow_to_close()).body_iterator
        assert await body.__anext__() == "a"
        before = ticks
        await body.aclose()                 # 客户端断开
        del body
        gc.collect()
        await asyncio.sleep(0)
        during = ticks - before
        task.cancel()
        return during

    during = asyncio.run(main())
    assert closed == [True]                 # 收尾做完了
    assert during >= 15, f"收尾的 0.4 秒里事件循环只转了 {during} 次：被卡住了"


def test_a_plain_list_and_a_finished_stream_still_work():
    async def read(chunks):
        return [c async for c in sse_response(chunks).body_iterator]

    assert asyncio.run(read(["a", "b"])) == ["a", "b"]                      # 列表没有 close，也行
    assert asyncio.run(read(c for c in ("x", "y", "z"))) == ["x", "y", "z"]
