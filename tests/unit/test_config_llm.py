"""Config tests: LLM key fallback (LLM_API_KEY or OPENROUTER_API_KEY) and
per-role model selection. Offline, env-isolated."""

from __future__ import annotations

from app.config import Settings


def _fresh(monkeypatch, **env) -> Settings:
    for name in (
        "LLM_API_KEY", "OPENROUTER_API_KEY", "LLM_ENABLED", "LLM_PROVIDER",
        "LLM_MODEL", "LLM_RESEARCHER_MODEL", "LLM_BASE_URL", "APP_MODE",
        "QLOO_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings.from_env()


def test_researcher_model_defaults_to_main_model(monkeypatch) -> None:
    s = _fresh(monkeypatch, LLM_MODEL="google/gemma-4-31b-it:free")
    assert s.llm_researcher_model is None  # consumer falls back to llm_model


def test_researcher_model_override(monkeypatch) -> None:
    s = _fresh(
        monkeypatch,
        LLM_MODEL="google/gemma-4-31b-it:free",
        LLM_RESEARCHER_MODEL="nvidia/nemotron-3-super-120b-a12b:free",
    )
    assert s.llm_model == "google/gemma-4-31b-it:free"
    assert s.llm_researcher_model == "nvidia/nemotron-3-super-120b-a12b:free"


def test_openrouter_key_satisfies_flag_check(monkeypatch) -> None:
    # LLM_API_KEY absent but OPENROUTER_API_KEY present must pass the startup
    # check (same-value semantic keys, human's key lives under OpenRouter's name).
    s = _fresh(
        monkeypatch,
        LLM_ENABLED="true",
        OPENROUTER_API_KEY="sk-or-v1-placeholder",
    )
    assert s.validate_for_mode() == []


def test_no_keys_fails_flag_check(monkeypatch) -> None:
    s = _fresh(monkeypatch, LLM_ENABLED="true")
    problems = s.validate_for_mode()
    assert any("key" in p.lower() for p in problems)


def test_base_url_configurable(monkeypatch) -> None:
    s = _fresh(monkeypatch, LLM_BASE_URL="https://openrouter.ai/api/v1/")
    assert s.llm_base_url == "https://openrouter.ai/api/v1"
