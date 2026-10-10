"""模型服务调不通（余额用完、密钥不对、连不上）：认得出来、记下来给横幅用、页面上单独说。不联网、不连 Redis。"""
import httpx
import openai
import pytest

from app.config import settings
from app.llm import provider, status
from app.llm.client import LLM_DOWN, LLMError, unavailable_reason
from app.llm.provider import Provider
from tests.conftest import jd_item, jd_reply
from tests.test_llm_client import MESSAGES, Harness

_REQ = httpx.Request("POST", "https://api.deepseek.com/chat/completions")


def _status_error(code: int) -> openai.APIStatusError:
    return openai.APIStatusError("error", response=httpx.Response(code, request=_REQ), body=None)


@pytest.mark.parametrize("error, reason", [
    (_status_error(402), "余额不足（402）"),
    (_status_error(401), "密钥无效（401）"),
    (_status_error(503), "服务繁忙（503）"),
    (openai.APITimeoutError(request=_REQ), "连不上模型服务（APITimeoutError）"),
    (_status_error(400), None),                      # 请求本身的问题，不算服务不可用
    (TimeoutError("read timed out"), None),
])
def test_which_failures_mean_the_service_is_down(error, reason):
    assert unavailable_reason(error) == reason


def test_a_down_service_is_flagged_on_the_error_and_remembered_for_the_banner():
    h = Harness([_status_error(402), _status_error(400)])
    downs = []
    h.client._mark_down = downs.append
    with pytest.raises(LLMError) as e:
        h.client.invoke("diagnose", MESSAGES, prompt_version="v1")
    assert e.value.unavailable == "余额不足（402）" and downs == ["余额不足（402）"]
    with pytest.raises(LLMError) as e:
        h.client.invoke("diagnose", MESSAGES, prompt_version="v2")
    assert e.value.unavailable is None and downs == ["余额不足（402）"]       # 别的错误不记


# ───────────── llm/status.py：问余额接口，结论存 1 分钟 ─────────────

class FakeRedis:
    def __init__(self, broken=False):
        self.store, self.broken = {}, broken

    def get(self, key):
        if self.broken:
            raise ConnectionError("Redis 连不上")
        return self.store.get(key)

    def set(self, key, value, ex=None):
        if self.broken:
            raise ConnectionError("Redis 连不上")
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)


class FakeHttp:
    def __init__(self, reply, flaky=0):
        self.reply, self.calls, self.flaky = reply, 0, flaky        # flaky：前几次连不上
        self.urls: list[str] = []

    def get(self, url, **_):
        self.calls += 1
        self.urls.append(url)
        if self.calls <= self.flaky:
            raise httpx.ConnectTimeout("timed out")
        if isinstance(self.reply, Exception):
            raise self.reply
        code, body = self.reply
        return httpx.Response(code, json=body, request=httpx.Request("GET", url))


@pytest.fixture
def probe(monkeypatch):
    def setup(reply, redis=None, flaky=0):
        http, redis = FakeHttp(reply, flaky), redis or FakeRedis()
        monkeypatch.setattr(status, "redis_client", redis)
        monkeypatch.setattr(status, "http_client", lambda: http)
        monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "sk-test")
        return http, redis
    return setup


@pytest.mark.parametrize("reply, reason", [
    ((200, {"is_available": True}), None),
    ((200, {"is_available": False}), "余额不足"),
    ((401, {}), "密钥无效（401）"),
    (httpx.ConnectError("refused"), "连不上模型服务（ConnectError）"),
    ((500, {}), None),                               # 余额接口自己出了状况：按能用处理，不让横幅误报
])
def test_balance_probe(probe, reply, reason):
    probe(reply)
    assert status.unavailable_reason() == reason


def test_one_network_hiccup_does_not_raise_the_banner(probe):
    http, _ = probe((200, {"is_available": True}), flaky=1)
    assert status.unavailable_reason() is None and http.calls == 2
    http, _ = probe((200, {"is_available": True}), flaky=2)                # 两次都连不上才算
    assert status.unavailable_reason() == "连不上模型服务（ConnectTimeout）"


def test_the_answer_is_kept_for_a_minute_and_a_failed_call_overrides_it(probe):
    http, redis = probe((200, {"is_available": True}))
    assert status.unavailable_reason() is None and status.unavailable_reason() is None
    assert http.calls == 1                                        # 第二次直接用存下的
    status.mark_down("余额不足（402）")
    assert status.unavailable_reason() == "余额不足（402）" and http.calls == 1


def test_only_deepseek_has_a_balance_and_other_providers_are_just_pinged(probe):
    """管理端的「模型设置」页现问一次：DeepSeek 问余额接口，顺便拿到余额；别家只问模型列表，看密钥对不对、连不连得上。"""
    http, _ = probe((200, {"is_available": True, "balance_infos": [{"currency": "CNY", "total_balance": "0.85"}]}))
    assert status.check(provider.env_provider()) == (None, "¥0.85") and http.urls == ["https://api.deepseek.com/user/balance"]

    other = Provider(3, "bailian", "阿里云百炼", "https://dashscope.aliyuncs.com/compatible-mode/v1/", "qwen-plus", "sk-x", 1.0, 1.0)
    http, _ = probe((200, {"data": []}))
    assert status.check(other) == (None, None) and http.urls == ["https://dashscope.aliyuncs.com/compatible-mode/v1/models"]
    probe((401, {}))
    assert status.check(other) == ("密钥无效（401）", None)
    probe((404, {}))                                              # 这家没有模型列表接口：按能用处理，不误报
    assert status.check(other) == (None, None)
    probe(httpx.ConnectError("refused"))
    assert status.check(other) == ("连不上模型服务（ConnectError）", None)
    http, _ = probe((200, {}))
    assert status.check(Provider(3, "custom", "其他", "https://x.example.com/v1", "m", "", 1.0, 1.0)) == ("没有配置 API Key", None)
    assert http.calls == 0


def test_switching_provider_drops_the_remembered_answer(probe):
    http, _ = probe((200, {"is_available": True}))
    status.mark_down("余额不足（402）")
    assert status.unavailable_reason() == "余额不足（402）" and http.calls == 0
    status.forget()                                               # 换了 Key 或供应商：旧结论作废，下一次现问
    assert status.unavailable_reason() is None and http.calls == 1


def test_without_redis_it_still_answers(probe):
    http, _ = probe((200, {"is_available": False}), redis=FakeRedis(broken=True))
    assert status.unavailable_reason() == "余额不足" and status.unavailable_reason() == "余额不足"
    assert http.calls == 2
    status.mark_down("余额不足（402）")                            # 记不下也不抛
    status.forget()


def test_endpoint_needs_no_login(client, monkeypatch):
    monkeypatch.setattr(status, "unavailable_reason", lambda: "余额不足")
    assert client.get("/api/v1/system/llm").json()["data"] == {"available": False}
    monkeypatch.setattr(status, "unavailable_reason", lambda: None)
    assert client.get("/api/v1/system/llm").json()["data"] == {"available": True}


# ───────────── 页面上说的话 ─────────────

DOWN = LLMError("match 调用 deepseek-chat 失败：APIStatusError", unavailable="余额不足（402）")


def test_jd_parsing_says_the_service_is_down(client, auth_headers, fake_llm):
    body = {"title": "后端", "raw_text": "任职要求：熟悉 Redis，熟悉 MySQL，有缓存性能优化经验者优先，本科及以上学历。"}
    fake_llm.replies["_JdOut"] = [DOWN]
    r = client.post("/api/v1/jobs", headers=auth_headers, json=body).json()
    assert (r["code"], r["message"]) == (50002, LLM_DOWN)
    fake_llm.replies["_JdOut"] = [LLMError("上游超时")]                    # 别的失败照旧
    assert client.post("/api/v1/jobs", headers=auth_headers, json=body).json()["message"] == "调用大模型解析岗位失败，请稍后重试"
    fake_llm.replies["_JdOut"] = [jd_reply(jd_item("hard", "skill", "Redis", "熟悉 Redis", "熟悉 Redis"))]
    assert client.post("/api/v1/jobs", headers=auth_headers, json=body).json()["code"] == 0
