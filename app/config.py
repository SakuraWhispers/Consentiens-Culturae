"""Environment-based settings. No secrets in code (AGENTS.md hard rule 4)."""

from dataclasses import dataclass
import os


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def llm_api_key() -> str | None:
    """Semantic-key fallback: LLM_API_KEY first, then OPENROUTER_API_KEY.

    The human's OpenRouter key lives under OPENROUTER_API_KEY; either name
    satisfies the startup check. Values are never logged.
    """
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
                _env("LLM_BASE_URL", "https://api.openai.com/v1")
                or "https://api.openai.com/v1"
            ).rstrip("/"),
            llm_timeout_seconds=float(_env("LLM_TIMEOUT_SECONDS", "30") or 30),
        )

    def validate_for_mode(self) -> list[str]:
        """Return human-readable problems; fail before serving requests."""
        problems: list[str] = []
        known = ("fixture", "live")
        if self.app_mode not in known:
            problems.append(f"APP_MODE must be one of {known}, got '{self.app_mode}'")
        if self.app_mode == "live" and not _env("QLOO_API_KEY"):
            problems.append("APP_MODE=live requires QLOO_API_KEY in the environment")
        if self.llm_enabled and not llm_api_key():
            problems.append("LLM_ENABLED=true requires LLM_API_KEY (or OPENROUTER_API_KEY) in the environment")
        return problems


settings = Settings.from_env()
