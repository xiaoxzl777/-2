"""LLM 客户端测试：注入假的模型 / 缓存 / 限流 / 审计，不需要网络、Redis、MySQL。"""
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from app.llm.client import LLMClient, LLMError, current_run_id, invoke_json, parse_json
from app.llm.registry import estimate_cost


class Answer(BaseModel):
    verdict: str
    score: int


MESSAGES = [("system", "请以 json 作答"), ("user", "这条经历写得怎么样？")]


class FakeCache:
    def __init__(self):
        self.store: dict[str, dict] = {}

    def get(self, key):
        return self.store.get(key)

    def put(self, key, value):
        self.store[key] = value


class Harness:
    """记录一次次调用里发生了什么。"""

    def __init__(self, replies: list[str | Exception]):
        self.replies = list(replies)
        self.cache = FakeCache()
        self.audits: list[dict] = []
        self.acquired: list[str] = []
        self.model_calls = 0
        self.client = LLMClient(chat_factory=self._factory, cache=self.cache,
                                acquire=lambda provider, rpm: self.acquired.append(provider),
                                write_audit=self.audits.append)

    def _factory(self, model: str, temperature: float):
        self.model_calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        message = AIMessage(content=reply, usage_metadata={"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500},
                            response_metadata={"system_fingerprint": "fp_test"})
        return GenericFakeChatModel(messages=iter([message]))


def test_structured_call_parses_and_accounts():
    h = Harness(['{"verdict": "vague", "score": 3}'])
    r = h.client.invoke("diagnose", MESSAGES, prompt_version="v1", schema=Answer, ref=("diagnosis", 88))

    assert r.parsed == Answer(verdict="vague", score=3) and r.parse_error is None
    assert (r.token_input, r.token_output, r.cache_hit, r.model_version) == (1000, 500, False, "fp_test")
    assert r.cost == estimate_cost("deepseek-chat", 1000, 500) > 0
    assert h.acquired == ["deepseek"]
    assert h.audits == [{
        "scene": "diagnose", "ref_type": "diagnosis", "ref_id": 88, "provider": "deepseek",
        "model_name": "deepseek-chat", "prompt_version": "v1", "run_id": None,
        "model_version": "fp_test", "token_input": 1000, "token_output": 500, "cost": r.cost,
        "latency_ms": r.latency_ms,
    }]


def test_second_identical_call_is_served_from_cache_for_free():
    h = Harness(['{"verdict": "ok", "score": 5}'])
    first = h.client.invoke("diagnose", MESSAGES, prompt_version="v1", schema=Answer)
    second = h.client.invoke("diagnose", MESSAGES, prompt_version="v1", schema=Answer)

    assert h.model_calls == 1 and len(h.acquired) == 1            # 第二次没调模型、没占限流名额
    assert second.cache_hit and second.cost == 0 and second.parsed == first.parsed
    assert [a.get("cache_hit", False) for a in h.audits] == [False, True]   # 命中也记一行审计


@pytest.mark.parametrize(
    "change",
    [
        {"messages": [("system", "请以 json 作答"), ("user", "换了一个问题")]},
        {"prompt_version": "v2"},
        {"scene": "rewrite"},
        {"temperature": 0.3},
    ],
)
def test_anything_that_changes_the_prompt_misses_the_cache(change):
    h = Harness(['{"verdict": "a", "score": 1}', '{"verdict": "b", "score": 2}'])
    base = {"scene": "diagnose", "messages": MESSAGES, "prompt_version": "v1", "temperature": 0.0}
    first = h.client.invoke(base["scene"], base["messages"], prompt_version=base["prompt_version"], schema=Answer)
    kw = {**base, **change}
    second = h.client.invoke(kw["scene"], kw["messages"], prompt_version=kw["prompt_version"],
                             temperature=kw["temperature"], schema=Answer)
    assert h.model_calls == 2 and not second.cache_hit and second.parsed != first.parsed


@pytest.mark.parametrize("bad", ["", "   ", "抱歉我无法回答", '{"verdict": "x"}', '{"verdict": "x", "score": "很高"}'])
def test_bad_output_is_reported_not_raised_and_not_cached(bad):
    h = Harness([bad, '{"verdict": "ok", "score": 4}'])
    r = h.client.invoke("diagnose", MESSAGES, prompt_version="v1", schema=Answer)
    assert r.parsed is None and r.parse_error                      # 调用方据此带原因重试
    assert h.cache.store == {}

    retry = h.client.invoke("diagnose", MESSAGES, prompt_version="v1", schema=Answer)
    assert not retry.cache_hit and retry.parsed.score == 4


def test_code_fenced_json_is_accepted():
    parsed, error = parse_json('```json\n{"verdict": "ok", "score": 2}\n```', Answer)
    assert error is None and parsed.score == 2


def test_model_failure_is_audited_and_raised_as_llm_error():
    h = Harness([TimeoutError("read timed out")])
    with pytest.raises(LLMError):
        h.client.invoke("diagnose", MESSAGES, prompt_version="v1", schema=Answer)
    assert h.audits[0]["success"] is False and "TimeoutError" in h.audits[0]["error_msg"]
    assert h.cache.store == {}


def test_evaluation_runs_bypass_the_cache_and_are_tagged():
    h = Harness(['{"verdict": "a", "score": 1}', '{"verdict": "a", "score": 1}'])
    h.client.invoke("diagnose", MESSAGES, prompt_version="v1", schema=Answer)      # 先把缓存填上
    token = current_run_id.set("run-42")
    try:
        r = h.client.invoke("diagnose", MESSAGES, prompt_version="v1", schema=Answer)
    finally:
        current_run_id.reset(token)
    assert not r.cache_hit and h.model_calls == 2 and h.audits[-1]["run_id"] == "run-42"


def test_use_cache_false_and_plain_text_calls():
    h = Harness(["你好，请介绍一下这个项目。", "你好，请介绍一下这个项目。"])
    msgs = [("system", "你是面试官"), ("user", "开始")]
    a = h.client.invoke("iv_ask", msgs, prompt_version="v1", temperature=0.7, use_cache=False)
    b = h.client.invoke("iv_ask", msgs, prompt_version="v1", temperature=0.7, use_cache=False)
    assert a.text == b.text and a.parsed is None and a.parse_error is None
    assert h.model_calls == 2 and h.cache.store == {}


def test_json_mode_requires_the_word_json_in_the_prompt():
    h = Harness(['{"verdict": "a", "score": 1}'])
    with pytest.raises(ValueError, match="json"):
        h.client.invoke("diagnose", [("user", "评价一下")], prompt_version="v1", schema=Answer)
    assert h.model_calls == 0


# ───────────── 流式调用 ─────────────


class StreamingChat:
    """流式的假模型：按给定分块逐个吐，最后一块带 token 用量；fail_at 表示吐到第几块时连接断掉。"""

    def __init__(self, pieces: list[str], fail_at: int | None = None):
        self.pieces, self.fail_at, self.calls = pieces, fail_at, 0

    def stream(self, messages):
        from langchain_core.messages import AIMessageChunk

        self.calls += 1
        for i, piece in enumerate(self.pieces):
            if i == self.fail_at:
                raise ConnectionError("连接断了")
            last = i == len(self.pieces) - 1
            yield AIMessageChunk(
                content=piece,
                usage_metadata={"input_tokens": 800, "output_tokens": 60, "total_tokens": 860} if last else None,
                response_metadata={"system_fingerprint": "fp_s"} if last else {})


def _streaming(chat: StreamingChat, cache: FakeCache | None = None):
    audits: list[dict] = []
    client = LLMClient(chat_factory=lambda model, temperature: chat, cache=cache or FakeCache(),
                       acquire=lambda provider, rpm: None, write_audit=audits.append)
    return client, audits


def test_stream_yields_pieces_then_caches_and_accounts():
    chat, cache = StreamingChat(["【问题】", "这句", "太虚"]), FakeCache()
    client, audits = _streaming(chat, cache)
    assert list(client.stream("rewrite", MESSAGES, prompt_version="a1", ref=("finding", 7))) == ["【问题】", "这句", "太虚"]
    assert audits[-1]["scene"] == "rewrite" and audits[-1]["ref_id"] == 7 and audits[-1]["model_version"] == "fp_s"
    assert (audits[-1]["token_input"], audits[-1]["token_output"]) == (800, 60)
    assert audits[-1]["cost"] == estimate_cost("deepseek-chat", 800, 60) > 0

    # 同样的请求再来一次：缓存里一次给出全文，不再调模型，记一行 cache_hit
    assert list(client.stream("rewrite", MESSAGES, prompt_version="a1", ref=("finding", 7))) == ["【问题】这句太虚"]
    assert chat.calls == 1 and audits[-1]["cache_hit"] is True


def test_stream_failure_midway_is_audited_raised_and_not_cached():
    chat, cache = StreamingChat(["【问题】", "半截", "后面"], fail_at=2), FakeCache()
    client, audits = _streaming(chat, cache)
    got = []
    with pytest.raises(LLMError):
        for piece in client.stream("rewrite", MESSAGES, prompt_version="a1"):
            got.append(piece)
    assert got == ["【问题】", "半截"]                      # 已经吐出的部分照常到了调用方手里
    assert audits[-1]["success"] is False and "ConnectionError" in audits[-1]["error_msg"]
    assert cache.store == {}


def test_stream_closed_early_by_the_caller_is_still_audited():
    client, audits = _streaming(StreamingChat(["一", "二", "三"]))
    gen = client.stream("gap", MESSAGES, prompt_version="a1")
    assert next(gen) == "一"
    gen.close()                                            # 比如浏览器中途关了页面
    assert audits[-1]["success"] is False and "提前结束" in audits[-1]["error_msg"]


def test_invoke_json_retries_once_with_the_reason():
    """要求 JSON 的调用：不合格就把上一次的输出和原因发回去再试一次；两次都不合格返回 None 和原因。"""
    from tests.conftest import FakeLLM

    llm = FakeLLM({"Answer": ["不是 JSON", '{"verdict": "好", "score": 4}']})
    parsed, cost, error = invoke_json(llm, "demo", MESSAGES, schema=Answer, prompt_version="v1")
    assert parsed.score == 4 and error is None and round(cost, 6) == 0.002
    retry = llm.calls["Answer"][1]
    assert len(retry) == len(MESSAGES) + 2
    assert retry[-2] == ("assistant", "不是 JSON") and retry[-1][1].startswith("你上一次的输出无法使用")

    llm = FakeLLM({"Answer": ["坏的", "还是坏的"]})
    parsed, cost, error = invoke_json(llm, "demo", MESSAGES, schema=Answer, prompt_version="v1")
    assert parsed is None and error and len(llm.calls["Answer"]) == 2
