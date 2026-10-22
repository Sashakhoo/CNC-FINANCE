import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.providers.ai.anthropic import AnthropicProvider
from app.providers.ai.base import extract_json
from app.providers.ai.gemini import GeminiProvider
from app.providers.ai.openai import OpenAIProvider
from app.providers.base import (AuthError, BadResponse, MemoryCache, NotConfigured, ProviderError, ProviderState,
                                QuotaExceeded, RateLimited, TransientError)

KEY = "sk-test-SECRET-123"


class Out(BaseModel):
    industry: str
    score: int


def gemini_reply(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}}


def anthropic_reply(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5}}


def openai_reply(text: str) -> dict:
    return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5}}


CASES = [
    (GeminiProvider, "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent",
     gemini_reply),
    (AnthropicProvider, "https://api.anthropic.com/v1/messages", anthropic_reply),
    (OpenAIProvider, "https://api.openai.com/v1/responses", openai_reply),
]


class Recorder:
    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event)


@pytest.mark.parametrize("cls,url,reply", CASES)
async def test_structured_output_and_request_shape(cls, url, reply):
    rec = Recorder()
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(url).mock(return_value=httpx.Response(200, json=reply('{"industry": "Automation", "score": 80}')))
        p = cls(KEY, recorder=rec)
        out = await p.generate_structured("Classify.", "Text here", Out)
    assert out == Out(industry="Automation", score=80)
    req = route.calls.last.request
    assert KEY not in str(req.url)
    body = json.loads(req.content)
    assert "Text here" in json.dumps(body)
    if cls is GeminiProvider:
        assert req.headers["x-goog-api-key"] == KEY
        assert body["generationConfig"]["responseMimeType"] == "application/json"
    elif cls is AnthropicProvider:
        assert req.headers["x-api-key"] == KEY and req.headers["anthropic-version"]
        assert body["model"] == "claude-haiku-5-5"
    else:
        assert req.headers["authorization"] == f"Bearer {KEY}"
        assert body["model"] == "gpt-6-luna" and body["text"]["format"]["type"] == "json_object"
    assert len(rec.events) == 1 and rec.events[0].success and rec.events[0].meta["input_tokens"] == 10


@pytest.mark.parametrize("cls,url,reply", CASES)
async def test_repair_attempt_then_success(cls, url, reply):
    with respx.mock() as mock:
        route = mock.post(url).mock(side_effect=[
            httpx.Response(200, json=reply("Sure! Here you go: industry is Automation")),
            httpx.Response(200, json=reply('```json\n{"industry": "Automation", "score": 70}\n```')),
        ])
        out = await cls(KEY).generate_structured("s", "p", Out)
    assert out.score == 70 and route.call_count == 2
    assert "not valid" in json.loads(route.calls.last.request.content).__repr__()


@pytest.mark.parametrize("cls,url,reply", CASES)
async def test_bad_output_twice_raises(cls, url, reply):
    with respx.mock() as mock:
        mock.post(url).mock(return_value=httpx.Response(200, json=reply('{"industry": "X"}')))
        with pytest.raises(BadResponse):
            await cls(KEY).generate_structured("s", "p", Out)


@pytest.mark.parametrize("cls,url,reply", CASES)
async def test_cache_hit_skips_http(cls, url, reply):
    cache = MemoryCache()
    with respx.mock() as mock:
        route = mock.post(url).mock(return_value=httpx.Response(200, json=reply('{"industry": "A", "score": 1}')))
        p = cls(KEY, cache=cache)
        await p.generate_structured("s", "p", Out)
        await p.generate_structured("s", "p", Out)
        assert route.call_count == 1
        await p.generate_structured("s", "different prompt", Out)
        assert route.call_count == 2


@pytest.mark.parametrize("status,body,exc", [
    (401, {"error": {"message": f"bad key {KEY}"}}, AuthError),
    (429, {"error": {"message": "slow down"}}, RateLimited),
    (429, {"error": {"code": "insufficient_quota"}}, QuotaExceeded),
    (503, {"error": "overloaded"}, TransientError),
    (400, {"error": {"message": f"invalid request with {KEY}"}}, ProviderError),
])
@pytest.mark.parametrize("cls,url,reply", CASES)
async def test_error_typing_and_no_key_leak(cls, url, reply, status, body, exc):
    rec = Recorder()
    with respx.mock() as mock:
        mock.post(url).mock(return_value=httpx.Response(status, json=body, headers={"retry-after": "7"}))
        with pytest.raises(exc) as info:
            await cls(KEY, recorder=rec).generate_structured("s", "p", Out)
    assert KEY not in str(info.value)
    assert info.value.http_status == status
    if exc is RateLimited:
        assert info.value.retry_after == 7.0
    assert rec.events[0].success is False and rec.events[0].error_type == exc.error_type


@pytest.mark.parametrize("cls,url,reply", CASES)
async def test_timeout_is_transient(cls, url, reply):
    with respx.mock() as mock:
        mock.post(url).mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(TransientError):
            await cls(KEY).generate_structured("s", "p", Out)


@pytest.mark.parametrize("cls", [GeminiProvider, AnthropicProvider, OpenAIProvider])
async def test_not_configured(cls):
    p = cls("")
    assert not p.is_configured()
    assert (await p.test_connection()).state == ProviderState.NOT_CONFIGURED
    with pytest.raises(NotConfigured):
        await p.generate_structured("s", "p", Out)


@pytest.mark.parametrize("cls,ping", [
    (GeminiProvider, "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite"),
    (AnthropicProvider, "https://api.anthropic.com/v1/models/claude-haiku-5-5"),
    (OpenAIProvider, "https://api.openai.com/v1/models/gpt-6-luna"),
])
async def test_test_connection(cls, ping):
    with respx.mock() as mock:
        mock.get(ping).mock(side_effect=[httpx.Response(200, json={}), httpx.Response(401, json={})])
        ok = await cls(KEY).test_connection()
        bad = await cls(KEY).test_connection()
    assert ok.state == ProviderState.CONNECTED and ok.http_status == 200
    assert bad.state == ProviderState.ERROR and bad.http_status == 401


async def test_model_override():
    with respx.mock() as mock:
        route = mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json=anthropic_reply('{"industry": "A", "score": 1}')))
        await AnthropicProvider(KEY, model="claude-sonnet-5-5").generate_structured("s", "p", Out)
    assert json.loads(route.calls.last.request.content)["model"] == "claude-sonnet-5-5"


async def test_gemini_blocked_prompt_is_bad_response():
    with respx.mock() as mock:
        mock.post(CASES[0][1]).mock(return_value=httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}))
        with pytest.raises(BadResponse, match="SAFETY"):
            await GeminiProvider(KEY).generate_structured("s", "p", Out)


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": 2}\n```') == {"a": 2}
    assert extract_json('Here: {"a": 3} done') == {"a": 3}
