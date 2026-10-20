"""Unit tests for the API-side G3 LLM hook wiring (offline, no network)."""

from app.agents.llm_client import AgentLLMError
from app.config import Settings
from app.services.llm_hooks import (
    attribute_search_calls,
    build_hooks,
    paced,
    resolve_pools,
)


def _settings(**overrides) -> Settings:
    from app.config import _env

    base = {
        "LLM_ENABLED": "true",
        "LLM_PROVIDER": "google",
        "LLM_MODEL": "models/gemma-4-26b-a4b-it",
        "LLM_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY": "gk_test",
        "LLM_RESEARCHER_MODEL": "nvidia/nemotron-3-super-120b-a12b:free",
        "LLM_RESEARCHER_BASE_URL": "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY": "ork_test",
    }
    base.update({k: v for k, v in overrides.items() if v is not None})
    import os

    saved = {k: os.environ.get(k) for k in list(base) + list(overrides)}
    os.environ.update(base)
    for k, v in overrides.items():
        if v is None:
            os.environ.pop(k, None)
    try:
        return Settings.from_env()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_build_hooks_disabled_is_config_error() -> None:
    s = _settings(LLM_ENABLED="false")
    try:
        build_hooks(s, [])
    except ValueError as exc:
        assert "not enabled" in str(exc)
    else:
        raise AssertionError("expected ValueError when LLM disabled")


def test_build_hooks_missing_key_is_loud() -> None:
    s = _settings(GEMINI_API_KEY="__unset__", LLM_RESEARCHER_MODEL=None,
                  LLM_RESEARCHER_BASE_URL="__unset__")
    try:
        build_hooks(s, [])
    except ValueError as exc:
        assert "no API key" in str(exc)
    else:
        raise AssertionError("expected ValueError for missing pool keys")


def test_resolve_pools_two_pool_generation_values() -> None:
    pools = resolve_pools(_settings())
    assert pools["main"]["model"] == "models/gemma-4-26b-a4b-it"
    # Google compat layer: bisected budget, no OpenRouter-only reasoning key.
    assert pools["main"]["gen"] == {"max_tokens": 16384}
    assert pools["researcher"]["model"] == "nvidia/nemotron-3-super-120b-a12b:free"
    assert pools["researcher"]["base_url"] == "https://openrouter.ai/api/v1"
    assert pools["researcher"]["gen"]["max_tokens"] == 32768
    assert pools["researcher"]["gen"]["reasoning"] == {"max_tokens": 16384}


def test_paced_retries_only_transient_errors(monkeypatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr("app.services.llm_hooks.time.sleep", waits.append)

    calls = {"n": 0}

    def transient(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise AgentLLMError("LLM HTTP 429: rate limited")
        return "ok"

    assert paced(transient)() == "ok"
    assert calls["n"] == 2 and waits == [70.0]

    def permanent(*args, **kwargs):
        raise AgentLLMError("LLM returned unusable output: schema")

    import pytest

    with pytest.raises(AgentLLMError, match="unusable output"):
        paced(permanent)()
    assert calls["n"] == 2  # no retry on non-transient failure


def test_attribute_search_calls_owner_mapping() -> None:
    calls = [
        {"endpoint": "search", "params": {"query": "Mock Studio Notebooks"}},
        {"endpoint": "search", "params": {"query": "ink pens and luxury pen"}},
        {"endpoint": "insights",
         "params": {"filter.type": "urn:entity:place",
                    "filter.tags": "urn:tag:category:place:stationery_store"}},
    ]
    concepts = [("A", "Mock Studio Notebooks"), ("B", "Mock Luxury Pen")]
    mapped = attribute_search_calls(calls, concepts)
    # Unique-name match attributes; ambiguous/non-matching stay shared (None).
    assert mapped[0][0] == "A"
    assert mapped[1][0] is None  # "pen" alone -> concept names: no unique hit
    assert mapped[2][0] is None
