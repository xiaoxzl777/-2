"""压测的两个场景（Locust，装在项目外面：pip install locust）。先跑 prepare.py seed 和 use-fake，再：

    # 场景一 读接口：很多人同时刷「我的投递」「我的简历」、打开结果页（都不调模型）
    locust -f scripts/loadtest/locustfile.py --headless -H http://127.0.0.1:8000 -u 100 -r 50 -t 60s --csv out Reader
    # 场景二 整条投递：N 个人同时点「投递」，各自盯着进度条等结果（模型是 fake_llm.py）
    locust -f scripts/loadtest/locustfile.py --headless -H http://127.0.0.1:8000 -u 30 -r 30 -t 15m --csv out Applier

环境变量：
    LT_THINK   场景一每两次操作之间停多久（秒），默认 1-2；设成 0 = 不停，用来找每秒最多能处理多少
    LT_ROUND   场景二第几轮（默认 0）：每轮给每个人换一组（简历, 岗位），配合 prepare.py flush 保证每次调用都真发出去
    LT_WATCH   场景二怎么等结果：sse（默认，读进度流）/ poll（每 3 秒查一次，页面连不上进度流时的做法）
    LT_ACCOUNTS  只用前 N 个临时账号（默认全部）。场景一用它让所有人都落在投过几次的账号上，列表和结果页才有内容
    LT_OUT     结束时把每类请求的次数、失败数、每秒几次、响应时间（毫秒）写成一份 JSON 到这个路径
"""
from __future__ import annotations

import itertools
import json
import os
import time
from pathlib import Path

from locust import HttpUser, between, constant, events, task
from locust.exception import StopUser

STATE = json.loads((Path(__file__).resolve().parents[3] / "data" / "eval_runs" / "loadtest-state.json")
                   .read_text(encoding="utf-8"))
ACCOUNTS, JOBS = STATE["users"], STATE["jobs"]
SHARED = int(os.environ.get("LT_ACCOUNTS", len(ACCOUNTS)))    # 只用前几个账号（场景一：让大家都落在投过几次的账号上）
ROUND = int(os.environ.get("LT_ROUND", "0"))
WATCH = os.environ.get("LT_WATCH", "sse")
_low, _, _high = os.environ.get("LT_THINK", "1-2").partition("-")
THINK = constant(0) if float(_low) == 0 else between(float(_low), float(_high or _low))

_seats = itertools.count()       # 每个模拟用户占一个临时账号
_finished = itertools.count(1)   # 场景二：投完的人数，都投完就提前收工


@events.test_stop.add_listener
def _write_summary(environment, **_) -> None:
    """Locust 自带的 CSV 在提前收工时会写不全，而且中文名字按系统编码写；这里自己写一份。"""
    out = os.environ.get("LT_OUT")
    if not out:
        return
    rows = [{"type": e.method, "name": e.name, "count": e.num_requests, "failed": e.num_failures,
             "per_second": round(e.total_rps, 1), "avg": round(e.avg_response_time),
             "p50": e.get_response_time_percentile(0.5), "p95": e.get_response_time_percentile(0.95),
             "p99": e.get_response_time_percentile(0.99), "max": round(e.max_response_time or 0)}
            for e in [*environment.stats.entries.values(), environment.stats.total]]
    errors = [{"name": e.name, "error": str(e.error)[:200], "count": e.occurrences} for e in environment.stats.errors.values()]
    Path(out).write_text(json.dumps({"rows": rows, "errors": errors}, ensure_ascii=False, indent=1), encoding="utf-8")


class _Account(HttpUser):
    abstract = True

    def on_start(self) -> None:
        self.seat = next(_seats)
        account = ACCOUNTS[self.seat % SHARED]
        self.resumes = account["resumes"]
        self.client.headers["Authorization"] = f"Bearer {account['token']}"
        self.client.trust_env = False       # 本机有系统代理，走代理访问 localhost 会被拒


class Reader(_Account):
    """场景一：登录后的人在几个页面之间来回看。"""

    wait_time = THINK
    applies: list[int] = []

    @task(3)
    def my_applies(self) -> None:
        reply = self.client.get("/api/v1/apply?page_size=100", name="我的投递 GET /apply")
        if reply.ok:
            self.applies = [item["id"] for item in reply.json()["data"]["items"]]

    @task(2)
    def my_resumes(self) -> None:
        self.client.get("/api/v1/resumes?page_size=100", name="我的简历 GET /resumes")

    @task(3)
    def result_page(self) -> None:
        if self.applies:
            apply_id = self.applies[next(_seats) % len(self.applies)]
            self.client.get(f"/api/v1/apply/{apply_id}", name="结果页 GET /apply/[id]")

    @task(2)
    def resume_blocks(self) -> None:
        resume_id = self.resumes[next(_seats) % len(self.resumes)]
        self.client.get(f"/api/v1/resumes/{resume_id}/blocks", name="简历原文 GET /resumes/[id]/blocks")


class Applier(_Account):
    """场景二：每人投一次，等到出结果（或失败）为止。"""

    wait_time = constant(0)

    @task
    def apply_once(self) -> None:
        resume = self.resumes[self.seat % len(self.resumes)]
        job = JOBS[(self.seat // len(self.resumes) + ROUND * 7) % len(JOBS)]     # 前 简历数 × 岗位数 个人，组合不重样
        started = time.perf_counter()
        outcome = "没投出去"
        try:
            reply = self.client.post("/api/v1/apply", json={"resume_id": resume, "job_id": job}, name="点投递 POST /apply")
            if reply.ok and reply.json().get("code") == 0:
                apply_id = reply.json()["data"]["id"]
                outcome = self._poll(apply_id) if WATCH == "poll" else self._stream(apply_id)
        except Exception as e:  # noqa: BLE001 —— 连接被服务端断开之类：记成失败。不接住的话 Locust 会让这个人再投一次
            outcome = f"连接出错（{type(e).__name__}）"
        finally:
            events.request.fire(request_type="整条", name="从点投递到出结果", response_length=0, context={},
                                response_time=(time.perf_counter() - started) * 1000,
                                exception=None if outcome == "done" else RuntimeError(outcome))
            if next(_finished) >= self.environment.runner.target_user_count:
                self.environment.runner.quit()
        raise StopUser()

    def _stream(self, apply_id: int) -> str:
        """读进度流直到 done / error。这一行统计的是「连上进度流要多久」，整条的时间在上面单独记。"""
        with self.client.get(f"/api/v1/tasks/apply/{apply_id}/stream", stream=True, timeout=(30, 700),
                             name="连上进度流 GET /tasks/apply/[id]/stream", catch_response=True) as stream:
            if not stream.ok:
                stream.failure(f"HTTP {stream.status_code}")
                return f"进度流 HTTP {stream.status_code}"
            for line in stream.iter_lines(decode_unicode=True):
                if line and line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                    if event in ("done", "error"):
                        return "done" if event == "done" else "分析失败"
            return "进度流断了"

    def _poll(self, apply_id: int) -> str:
        for _ in range(240):
            time.sleep(3)
            reply = self.client.get(f"/api/v1/apply/{apply_id}", name="轮询结果 GET /apply/[id]")
            stage = reply.json()["data"]["stage"] if reply.ok else None
            if stage in ("done", "failed"):
                return "done" if stage == "done" else "分析失败"
        return "等了 12 分钟还没结果"
