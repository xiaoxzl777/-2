"""Redis 上的两件事：调模型前按分钟限流、模型结果缓存的容错。用字典假装 Redis、用假时钟代替真的等。"""
import pytest

from app.cache import llm_cache, ratelimit


class FakeRedis:
    def __init__(self, broken=False):
        self.data: dict[str, object] = {}
        self.ttl: dict[str, int | None] = {}
        self.broken = broken

    def _check(self):
        if self.broken:
            raise ConnectionError("Redis 连不上")

    def incr(self, key):
        self._check()
        self.data[key] = int(self.data.get(key, 0)) + 1
        return self.data[key]

    def expire(self, key, seconds):
        self.ttl[key] = seconds

    def get(self, key):
        self._check()
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self._check()
        self.data[key], self.ttl[key] = value, ex


class Clock:
    """sleep 不真的睡，只把时间往前拨。起点落在某一分钟的第 12 秒。"""

    def __init__(self):
        self.now, self.slept = 60 * 16666 + 12.0, []

    def time(self):
        return self.now

    monotonic = time

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def limiter(monkeypatch):
    redis, clock = FakeRedis(), Clock()
    monkeypatch.setattr(ratelimit, "redis_client", redis)
    monkeypatch.setattr(ratelimit, "time", clock)
    return redis, clock


def test_a_full_minute_makes_the_next_call_wait_for_the_next_one(limiter):
    redis, clock = limiter
    ratelimit.acquire("deepseek", 2)
    ratelimit.acquire("deepseek", 2)
    ratelimit.acquire("siliconflow", 2)                       # 各服务商各算各的
    assert clock.slept == []

    ratelimit.acquire("deepseek", 2)                          # 这一分钟的 2 个名额用完了：睡到下一分钟开始
    assert clock.slept == [pytest.approx(48.05)]
    assert redis.data == {"ratelimit:deepseek:16666": 3, "ratelimit:siliconflow:16666": 1, "ratelimit:deepseek:16667": 1}
    assert set(redis.ttl.values()) == {120}                   # 每个桶过两分钟自己过期，不用清


def test_waiting_gives_up_after_two_minutes(limiter):
    _, clock = limiter
    with pytest.raises(ratelimit.RateLimitTimeout, match="deepseek"):
        ratelimit.acquire("deepseek", 0)                      # 每一分钟都是满的
    # 每次醒来先再抢一次，抢不到、又已经等过了 120 秒才放弃：所以实际等到的是 120 秒之后的那个整分钟
    assert len(clock.slept) == 3 and 120 < sum(clock.slept) < 180


def test_cached_answers_come_back_and_expire(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(llm_cache, "redis_client", redis)
    key = llm_cache.make_key("match", "deepseek-chat", "match-v1", "同一段提示词")
    assert key != llm_cache.make_key("match", "deepseek-chat", "match-v1", "换了一个字的提示词")
    assert llm_cache.get(key) is None

    llm_cache.put(key, {"text": "判定结果", "model_version": "fp"})
    assert llm_cache.get(key) == {"text": "判定结果", "model_version": "fp"}
    assert redis.ttl[key] == llm_cache.settings.LLM_CACHE_TTL_SECONDS


def test_a_broken_cache_counts_as_a_miss_instead_of_failing_the_call(monkeypatch):
    """缓存保护的是付费调用：Redis 读写出错只当没命中、照常去调模型，不能让整次诊断跟着失败。"""
    monkeypatch.setattr(llm_cache, "redis_client", FakeRedis(broken=True))
    assert llm_cache.get("llm:x") is None
    llm_cache.put("llm:x", {"text": "t"})                     # 不抛


def test_the_shared_http_client_is_built_once_when_many_threads_ask_at_the_same_time(monkeypatch):
    """共用的 HTTP 客户端只能建一个：服务刚起来就来一批投递时，几十个线程会同时第一次来要。
    各建各的不光白白多加载几十遍证书，Windows 上并发加载系统证书还会让进程直接崩掉（压测测出来的）。"""
    import threading
    import time

    from app.llm import registry

    built = []

    class SlowClient:
        def __init__(self, **_):
            time.sleep(0.05)        # 建得慢一点，让别的线程有机会在它建好之前也闯进来
            built.append(self)

    monkeypatch.setattr(registry, "_client", None)
    monkeypatch.setattr(registry.httpx, "Client", SlowClient)
    together, got = threading.Barrier(20), []

    def ask():
        together.wait()
        got.append(registry.http_client())

    threads = [threading.Thread(target=ask) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(built) == 1 and all(client is built[0] for client in got)


def test_short_redis_operations_queue_for_a_connection_and_subscriptions_use_their_own_pool(monkeypatch):
    """缓存、限流这些一问一答的操作：连接都被占着时排队等，不能直接报错（30 人同时投递时，三百来个并行调用一起来占
    限流名额，默认的连接池到 100 个就抛 Too many connections，分析成片失败）。进度流的订阅长期占着连接，另用一个池。"""
    import redis

    from app.cache import pubsub
    from app.cache.redis_client import pubsub_client, redis_client

    assert isinstance(redis_client.connection_pool, redis.BlockingConnectionPool)
    assert pubsub_client.connection_pool is not redis_client.connection_pool

    opened = []

    class FakePubSub:
        def subscribe(self, name):
            opened.append(name)

    class FakeClient:
        def pubsub(self, **_):
            return FakePubSub()

    monkeypatch.setattr(pubsub, "redis_client", None)           # 订阅要是还去用它，这里就会报错
    monkeypatch.setattr(pubsub, "pubsub_client", FakeClient())
    pubsub.Subscription("apply:7")
    assert opened == ["task:apply:7"]
