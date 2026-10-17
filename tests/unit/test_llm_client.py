"""LLM client tests: base-URL selection (OpenAI default / OpenRouter-capable)
and error mapping. Offline via httpx MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from app.agents.llm_client import AgentLLMError, complete_json

_OPENAI = "https://api.openai.com/v1"
_OPENROUTER = "https://openrouter.ai/api/v1"


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": "{\"ok\": true}"}}]},
        request=httpx.Request("POST", "https://example.invalid/chat/completions"),
    )


def _transport_capture() -> tuple[httpx.MockTransport, list[str]]:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return _ok_response()

    return httpx.MockTransport(handler), urls


def test_default_base_url_is_openai() -> None:
    transport, urls = _transport_capture()
    with httpx.Client(transport=transport) as client:
        complete_json("k", "m", "sys", {"x": 1}, client=client)
    assert urls == [f"{_OPENAI}/chat/completions"]


def test_custom_base_url_is_used() -> None:
    # OpenRouter is OpenAI-compatible: same path suffix, different host.
    transport, urls = _transport_capture()
    with httpx.Client(transport=transport) as client:
        complete_json("k", "m", "sys", {"x": 1}, base_url=_OPENROUTER, client=client)
    assert urls == [f"{_OPENROUTER}/chat/completions"]


def test_trailing_slash_is_normalized() -> None:
    transport, urls = _transport_capture()
    with httpx.Client(transport=transport) as client:
        complete_json("k", "m", "sys", {"x": 1}, base_url=_OPENROUTER + "/", client=client)
    assert urls == [f"{_OPENROUTER}/chat/completions"]


def test_auth_error_raises_named_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AgentLLMError, match="rejected the key"):
            complete_json("k", "m", "sys", {"x": 1}, client=client)


def test_unparseable_content_raises_named_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AgentLLMError, match="unusable output"):
            complete_json("k", "m", "sys", {"x": 1}, client=client)


def _body_capture() -> tuple[httpx.MockTransport, list[dict]]:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _ok_response()

    return httpx.MockTransport(handler), bodies


def test_reasoning_and_max_tokens_sent_when_given() -> None:
    transport, bodies = _body_capture()
    with httpx.Client(transport=transport) as client:
        complete_json(
            "k", "m", "sys", {"x": 1},
            client=client,
            reasoning={"effort": "high"},
            max_tokens=24000,
        )
    body = bodies[0]
    assert body["reasoning"] == {"effort": "high"}
    assert body["max_tokens"] == 24000


def test_base_params_absent_by_default() -> None:
    transport, bodies = _body_capture()
    with httpx.Client(transport=transport) as client:
        complete_json("k", "m", "sys", {"x": 1}, client=client)
    body = bodies[0]
    assert "reasoning" not in body
    assert "max_tokens" not in body


def test_no_leaderboard_headers_sent() -> None:
    # Attribution headers (HTTP-Referer / X-Title) would count us for the
    # OpenRouter leaderboards; the human asked to stay off them.
    transport, bodies = _body_capture()
    seen: dict[str, str] = {}

    def handler2(request: httpx.Request) -> httpx.Response:
        seen.update({k.lower(): v for k, v in request.headers.items() if k.lower() in
                     ("http-referer", "x-title")})
        bodies.append(json.loads(request.content))
        return _ok_response()

    with httpx.Client(transport=httpx.MockTransport(handler2)) as client:
        complete_json("k", "m", "sys", {"x": 1}, client=client)
    assert seen == {}, (
        "OpenRouter attribution headers must not be sent (human: stay off leaderboards)"
    )
