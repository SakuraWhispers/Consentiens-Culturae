"""Minimal LLM client (G3): httpx only, no SDK dependency.

OpenAI-compatible chat-completions endpoint with JSON-object response mode.
Sends structured data + prompts only — never keys, never raw Qloo payloads
(normalized summaries and computed scores only, per qloo-api-notes §7).
One call per agent step; retries and fallbacks live in the coordinator.
"""

from __future__ import annotations

import json
from typing import Any

import httpx


class AgentLLMError(RuntimeError):
    """LLM call failed or returned unusable output."""


DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"


def complete_json(
    api_key: str,
    model: str,
    system: str,
    user_payload: dict[str, Any],
    timeout_seconds: float = 30.0,
    client: httpx.Client | None = None,
    base_url: str = DEFAULT_LLM_BASE_URL,
    max_tokens: int | None = None,
    reasoning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST one chat-completion request; return the parsed JSON object.

    Any OpenAI-compatible endpoint works (OpenAI default; OpenRouter via
    base_url="https://openrouter.ai/api/v1"). Keys and payloads travel in
    headers/body only — never logged. No OpenRouter attribution headers are
    sent (HTTP-Referer/X-Title) — the human asked to stay off the leaderboards.
    `max_tokens` and `reasoning` (e.g. {"effort": "high"} or {"max_tokens": N})
    are forwarded verbatim when set; per OpenRouter, reasoning tokens count
    against max_tokens, so callers must size max_tokens above the reasoning
    budget or the final JSON gets truncated.
    """
    own_client = client is None
    url = f"{base_url.rstrip('/')}/chat/completions"
    request_body: dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload)[:12000]},
        ],
    }
    if max_tokens is not None:
        request_body["max_tokens"] = max_tokens
    if reasoning is not None:
        request_body["reasoning"] = reasoning
    http = client or httpx.Client(timeout=timeout_seconds)
    try:
        resp = http.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=request_body,
        )
    except httpx.TimeoutException as exc:
        raise AgentLLMError(f"LLM timeout after {timeout_seconds}s") from exc
    except httpx.RequestError as exc:
        raise AgentLLMError(f"LLM request error: {type(exc).__name__}") from exc
    finally:
        if own_client:
            http.close()
    if resp.status_code in (401, 403):
        raise AgentLLMError("LLM rejected the key")
    if resp.status_code == 429:
        detail = resp.text[:300]
        raise AgentLLMError(f"LLM rate limited: {detail}")
    if resp.status_code >= 400:
        detail = resp.text[:300]
        raise AgentLLMError(f"LLM HTTP {resp.status_code}: {detail}")
    try:
        body = resp.json()
        choice = body["choices"][0]
        message = choice.get("message", {})
        content = message.get("content")
        finish_reason = choice.get("finish_reason")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AgentLLMError(
            f"LLM returned unusable envelope: keys={list(body) if isinstance(body, dict) else type(body).__name__}"
        ) from exc
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError) as exc:
        raise AgentLLMError(
            "LLM returned unusable output: "
            f"finish_reason={finish_reason!r}, has_reasoning_field={'reasoning' in message}, "
            f"content_head={(content or '')[:300]!r}"
        ) from exc
    if not isinstance(parsed, dict):
        raise AgentLLMError(
            f"LLM returned a non-object: finish_reason={finish_reason!r}, "
            f"parsed_type={type(parsed).__name__}, content_head={(content or '')[:300]!r}"
        )
    return parsed


__all__ = ["AgentLLMError", "complete_json", "DEFAULT_LLM_BASE_URL"]
