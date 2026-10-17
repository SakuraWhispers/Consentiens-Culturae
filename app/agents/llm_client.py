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
) -> dict[str, Any]:
    """POST one chat-completion request; return the parsed JSON object.

    Any OpenAI-compatible endpoint works (OpenAI default; OpenRouter via
    base_url="https://openrouter.ai/api/v1"). Keys and payloads travel in
    headers/body only — never logged.
    """
    own_client = client is None
    url = f"{base_url.rstrip('/')}/chat/completions"
    http = client or httpx.Client(timeout=timeout_seconds)
    try:
        resp = http.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(user_payload)[:12000]},
                ],
            },
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
        raise AgentLLMError("LLM rate limited")
    if resp.status_code >= 400:
        raise AgentLLMError(f"LLM HTTP {resp.status_code}")
    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AgentLLMError("LLM returned unusable output") from exc
    if not isinstance(parsed, dict):
        raise AgentLLMError("LLM returned a non-object")
    return parsed


__all__ = ["AgentLLMError", "complete_json", "DEFAULT_LLM_BASE_URL"]
