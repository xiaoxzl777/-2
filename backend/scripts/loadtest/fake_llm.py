"""压测用的假模型服务：接口和 OpenAI 兼容，等一会儿再回一段格式正确的假结果，不花钱。

    python scripts/loadtest/fake_llm.py [--port 9100] [--latency 1.5-2.5]

后端不用改代码：在管理端把对话模型换成它（prepare.py use-fake），缓存、限流、记账都照常走，测的就是线上那条路。
只认得投递用到的三种请求：管理端的试连、诊断审一条经历描述、匹配判几条要求；别的一律回空对象。
--latency 是每次调用等多久（秒，在这个范围里随机取），模仿真模型的速度：评测里 DeepSeek 一次调用约 2 秒。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import time

import uvicorn
from fastapi import FastAPI, Request

MODEL = "loadtest-fake"

app = FastAPI()
latency = (1.5, 2.5)
stats = {"calls": 0, "running": 0, "peak": 0}      # 一共调了几次、现在有几个在等、同时在等的最多几个


def answer(messages: list[dict]) -> dict:
    """按提示词的样子认出是哪种请求（提示词模板见 app/llm/prompts.py），回一份过得了校验的结果。"""
    asked = [m.get("content") or "" for m in messages if m.get("role") == "user"]
    first = asked[0] if asked else ""
    if '{"ok": true}' in first:                                    # 管理端保存前的试连
        return {"ok": True}
    if "【原文】" in first and "【规则引擎已检出】" in first:          # 诊断：审一条经历描述
        if len(asked) > 1:                                         # 被打回重试了：不再报
            return {"findings": []}
        text = first.split("【原文】\n", 1)[1].split("\n【规则引擎已检出】", 1)[0].strip()
        quote = text.splitlines()[0][:12] if text else ""          # 引用必须是原文里连续的一段，否则会被作废、触发重试
        if len(quote) < 6:
            return {"findings": []}
        return {"findings": [{"risk_type": "vague", "severity": "low", "evidence_quote": quote,
                              "reason": "压测用的假结果", "suggestion": ""}]}
    if "【岗位要求】" in first and "【简历全文】" in first:            # 匹配：每条要求给一个结论
        listing = first.split("【岗位要求】\n", 1)[1].split("\n【简历全文】", 1)[0]
        ids = [int(n) for n in re.findall(r"^(\d+)\. ", listing, flags=re.M)]
        return {"results": [{"id": i, "status": "miss", "reason": "压测用的假结果"} for i in ids]}
    return {}


@app.post("/v1/chat/completions")
async def chat(request: Request) -> dict:
    body = await request.json()
    messages = body.get("messages") or []
    stats["calls"] += 1
    stats["running"] += 1
    stats["peak"] = max(stats["peak"], stats["running"])
    try:
        await asyncio.sleep(random.uniform(*latency))
    finally:
        stats["running"] -= 1
    content = json.dumps(answer(messages), ensure_ascii=False)
    asked = sum(len(str(m.get("content") or "")) for m in messages)       # token 数粗略估一个，记账那一步照常有数可记
    return {"id": f"fake-{stats['calls']}", "object": "chat.completion", "created": int(time.time()),
            "model": body.get("model") or MODEL,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": asked, "completion_tokens": len(content), "total_tokens": asked + len(content)}}


@app.get("/v1/models")
def models() -> dict:
    """后端探测「模型服务能不能用」时问的是这个接口。"""
    return {"object": "list", "data": [{"id": MODEL, "object": "model"}]}


@app.get("/stats")
def show_stats() -> dict:
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="压测用的假模型服务")
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--latency", default="1.5-2.5", help="每次调用等多久（秒），如 1.5-2.5；0 = 不等")
    args = parser.parse_args()
    low, _, high = args.latency.partition("-")
    latency = (float(low), float(high or low))
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
