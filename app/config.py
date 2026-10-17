"""Environment-based settings. No secrets in code (AGENTS.md hard rule 4)."""

from dataclasses import dataclass
import os


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


# Default OpenAI-compatible base URLs per LLM_PROVIDER (is_openai_compat=True).
_DEFAULT_LLM_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
}


def llm_api_key(provider: str | None = None) -> str | None:
    """Semantic-key fallback for the MAIN (analyst/critic) pool.

    provider "google" → GEMINI_API_KEY (Google AI Studio) or
    GOOGLE_AI_STUDIO_API_KEY. Any other provider → LLM_API_KEY or
    OPENROUTER_API_KEY (the human's OpenRouter key lives under both names).
    Values are never logged.
    """
    if (provider or "openai") == "google":
        return _env("GEMINI_API_KEY") or _env("GOOGLE_AI_STUDIO_API_KEY")
    return _env("LLM_API_KEY") or _env("OPENROUTER_API_KEY")


@dataclass(frozen=True)
class Settings:
    """Read once per process. Live mode with missing keys fails at startup."""

    app_mode: str = "fixture"  # "fixture" | "live"
    database_url: str = "sqlite:///./consentiens_culturae.db"
    qloo_base_url: str = "https://hackathon.api.qloo.com"
    qloo_timeout_seconds: float = 10.0
    qloo_max_calls_per_run: int = 10
    insufficient_coverage_threshold: float = 0.5
    # G3 agent roles: flag-gated, deterministic fallback is the default.
    llm_enabled: bool = False
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_researcher_model: str | None = None  # None = use llm_model
    llm_base_url: str = "https://api.openai.com/v1"
    # Researcher overrides — the researcher may ride a DIFFERENT pool (e.g.
    # OpenRouter Nemotron) than analyst/critic (e.g. Google AI Studio Gemma).
    llm_researcher_base_url: str | None = None  # None = llm_base_url
    llm_researcher_api_key_env: str | None = None  # NAME of a dedicated env var, optional
    llm_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_mode=(_env("APP_MODE", "fixture") or "fixture").lower(),
            database_url=_env("DATABASE_URL", "sqlite:///./consentiens_culturae.db") or "",
            qloo_base_url=(
                _env("QLOO_BASE_URL", "https://hackathon.api.qloo.com")
                or "https://hackathon.api.qloo.com"
            ).rstrip("/"),
            qloo_timeout_seconds=float(_env("QLOO_TIMEOUT_SECONDS", "10") or 10),
            qloo_max_calls_per_run=int(_env("QLOO_MAX_CALLS_PER_RUN", "10") or 10),
            insufficient_coverage_threshold=float(
                _env("INSUFFICIENT_COVERAGE_THRESHOLD", "0.5") or 0.5
            ),
            llm_enabled=(_env("LLM_ENABLED", "false") or "false").lower() == "true",
            llm_provider=(_env("LLM_PROVIDER", "openai") or "openai").lower(),
            llm_model=_env("LLM_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
            llm_researcher_model=_env("LLM_RESEARCHER_MODEL"),
            llm_base_url=(
                _env(
                    "LLM_BASE_URL",
                    _DEFAULT_LLM_BASE_URLS.get(
                        (_env("LLM_PROVIDER", "openai") or "openai").lower(),
                        "https://api.openai.com/v1",
                    ),
                )
                or "https://api.openai.com/v1"
            ).rstrip("/"),
            llm_researcher_base_url=(
                _env("LLM_RESEARCHER_BASE_URL").rstrip("/")
                if _env("LLM_RESEARCHER_BASE_URL")
                else None
            ),
            llm_researcher_api_key_env=_env("LLM_RESEARCHER_API_KEY_ENV"),
            llm_timeout_seconds=float(_env("LLM_TIMEOUT_SECONDS", "30") or 30),
        )

    def researcher_api_key(self) -> str | None:
        """Value for the RESEARCHER pool: a dedicated env var (named via
        LLM_RESEARCHER_API_KEY_ENV), else the OpenAI-family chain
        (LLM_API_KEY / OPENROUTER_API_KEY), else — when the researcher has no
        pool overrides of its own — the main provider's key (same pool)."""
        if self.llm_researcher_api_key_env and _env(self.llm_researcher_api_key_env):
            return _env(self.llm_researcher_api_key_env)
        oa_chain = _env("LLM_API_KEY") or _env("OPENROUTER_API_KEY")
        if oa_chain:
            return oa_chain
        if not (self.llm_researcher_model or self.llm_researcher_base_url):
            return llm_api_key(self.llm_provider)
        return None  # overrides point elsewhere but no key for that pool

    def researcher_base_url(self) -> str:
        if self.llm_researcher_base_url:
            return self.llm_researcher_base_url
        # A researcher without its own base rides the same pool as main. If
        # main moved to a non-OpenRouter provider, that base is wrong for
        # OpenRouter model ids — callers must set LLM_RESEARCHER_BASE_URL;
        # surface the situation rather than guess.
        return self.llm_base_url

    def validate_for_mode(self) -> list[str]:
        """Return human-readable problems; fail before serving requests."""
        problems: list[str] = []
        known = ("fixture", "live")
        if self.app_mode not in known:
            problems.append(f"APP_MODE must be one of {known}, got '{self.app_mode}'")
        if self.app_mode == "live" and not _env("QLOO_API_KEY"):
            problems.append("APP_MODE=live requires QLOO_API_KEY in the environment")
        if self.llm_enabled:
            if not llm_api_key(self.llm_provider):
                if self.llm_provider == "google":
                    problems.append(
                        "LLM_ENABLED=true with LLM_PROVIDER=google requires "
                        "GEMINI_API_KEY (or GOOGLE_AI_STUDIO_API_KEY) in the environment"
                    )
                else:
                    problems.append(
                        "LLM_ENABLED=true requires LLM_API_KEY (or OPENROUTER_API_KEY) "
                        "in the environment"
                    )
            # The researcher may ride a different pool; a dedicated var named
            # but unset, or overrides pointing elsewhere with no OpenAI-family
            # key, both make the researcher pool unresolvable.
            if not self.researcher_api_key():
                problems.append(
                    "LLM_ENABLED=true with a researcher pool requires "
                    "LLM_RESEARCHER_API_KEY_ENV, LLM_API_KEY, or OPENROUTER_API_KEY"
                )
        return problems


settings = Settings.from_env()
