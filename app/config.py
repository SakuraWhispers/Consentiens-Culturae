"""Environment-based settings. No secrets in code (AGENTS.md hard rule 4)."""

from dataclasses import dataclass
import os


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    """Read once per process. Live mode with missing keys fails at startup."""

    app_mode: str = "fixture"  # "fixture" | "live"
    database_url: str = "sqlite:///./culturefit.db"
    qloo_timeout_seconds: float = 10.0
    qloo_max_calls_per_run: int = 10
    insufficient_coverage_threshold: float = 0.5

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_mode=(_env("APP_MODE", "fixture") or "fixture").lower(),
            database_url=_env("DATABASE_URL", "sqlite:///./culturefit.db") or "",
            qloo_timeout_seconds=float(_env("QLOO_TIMEOUT_SECONDS", "10") or 10),
            qloo_max_calls_per_run=int(_env("QLOO_MAX_CALLS_PER_RUN", "10") or 10),
            insufficient_coverage_threshold=float(
                _env("INSUFFICIENT_COVERAGE_THRESHOLD", "0.5") or 0.5
            ),
        )

    def validate_for_mode(self) -> list[str]:
        """Return human-readable problems; fail before serving requests."""
        problems: list[str] = []
        known = ("fixture", "live")
        if self.app_mode not in known:
            problems.append(f"APP_MODE must be one of {known}, got '{self.app_mode}'")
        if self.app_mode == "live" and not _env("QLOO_API_KEY"):
            problems.append("APP_MODE=live requires QLOO_API_KEY in the environment")
        return problems


settings = Settings.from_env()
