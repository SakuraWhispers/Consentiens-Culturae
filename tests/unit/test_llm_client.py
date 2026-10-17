"""LLM client tests: base-URL selection (OpenAI default / OpenRouter-capable)
and error mapping. Offline via httpx MockTransport."""

from __future__ import annotations

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
