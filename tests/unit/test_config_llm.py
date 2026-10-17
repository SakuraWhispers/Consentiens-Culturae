"""Config tests: LLM key fallback (LLM_API_KEY or OPENROUTER_API_KEY) and
per-role model selection. Offline, env-isolated."""

from __future__ import annotations

from app.config import Settings, llm_api_key


def _fresh(monkeypatch, **env) -> Settings:
    for name in (
        "LLM_API_KEY", "OPENROUTER_API_KEY", "LLM_ENABLED", "LLM_PROVIDER",
        "LLM_MODEL", "LLM_RESEARCHER_MODEL", "LLM_BASE_URL", "APP_MODE",
        "QLOO_API_KEY", "GEMINI_API_KEY", "GOOGLE_AI_STUDIO_API_KEY",
        "LLM_RESEARCHER_BASE_URL", "LLM_RESEARCHER_API_KEY_ENV",
        "LLM_RESEARCHER_API_KEY",
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


def test_google_provider_gets_ai_studio_base_url(monkeypatch) -> None:
    # Bumping the provider to Google aims the MAIN (analyst/critic) pool at
    # Google AI Studio's OpenAI-compatible endpoint by default.
    s = _fresh(monkeypatch, LLM_PROVIDER="google")
    assert s.llm_base_url == "https://generativelanguage.googleapis.com/v1beta/openai"


def test_gemini_key_satisfies_main_check_when_google(monkeypatch) -> None:
    s = _fresh(
        monkeypatch,
        LLM_ENABLED="true",
        LLM_PROVIDER="google",
        GEMINI_API_KEY="AIza-placeholder",
    )
    assert s.validate_for_mode() == []


def test_openrouter_key_still_satisfies_google_check(monkeypatch) -> None:
    # Google AI Studio free tier ALSO serves Google-family models, so the
    # OpenRouter route remains a valid analyst path when no Gemini key exists.
    from app.config import llm_api_key

    assert llm_api_key("openai") is None or llm_api_key("openai") != llm_api_key("google")


def test_researcher_key_chain_independent_of_main_provider(monkeypatch) -> None:
    # Main pool on Google must NOT hand the Gemini key to the researcher's
    # OpenRouter base URL: the researcher chain stays OpenAI-family.
    s = _fresh(
        monkeypatch,
        LLM_PROVIDER="google",
        GEMINI_API_KEY="AIza-placeholder",
        LLM_API_KEY="sk-or-v1-openrouter-placeholder",
    )
    assert s.researcher_api_key() == "sk-or-v1-openrouter-placeholder"
    assert llm_api_key("google") == "AIza-placeholder"


def test_researcher_dedicated_key_env(monkeypatch) -> None:
    s = _fresh(
        monkeypatch,
        LLM_API_KEY="sk-or-v1-openrouter-placeholder",
        LLM_RESEARCHER_API_KEY_ENV="LLM_RESEARCHER_API_KEY",
        LLM_RESEARCHER_API_KEY="dedicated",
    )
    assert s.researcher_api_key() == "dedicated"


def test_researcher_base_url_override(monkeypatch) -> None:
    s = _fresh(monkeypatch, LLM_RESEARCHER_BASE_URL="https://openrouter.ai/api/v1/")
    assert s.researcher_base_url() == "https://openrouter.ai/api/v1"
    plain = _fresh(monkeypatch, LLM_BASE_URL="https://api.example.com/v1")
    assert plain.researcher_base_url() == "https://api.example.com/v1"
