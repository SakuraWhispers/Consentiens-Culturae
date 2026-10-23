"""In-process run limiter for the decision-run API.

Protects the free-model budget (human requirement, 2026-10-20): each run can
consume up to 10 Qloo calls and up to 9 LLM attempts, and the demo must not
allow parallel or rapid-fire runs. Enforcement: process-global (single-process
uvicorn), one run at a time, a configurable minimum gap between consecutive
run starts, and a per-UTC-day cap. Rejections surface as HTTP 429 with a
Retry-After header — never a silent drop. A second process-global instance
caps the attribute suggester (the same free-model budget, spent by a button
instead of a run).

Limits come from env: RUN_MIN_GAP_SECONDS (default 30), RUNS_PER_DAY
(default 50). Both floor at sane minimums; a value of "0" disables the cap
that it names (gap disabling still keeps the single-flight guard).
"""

from __future__ import annotations

import threading
import time
import os
from datetime import datetime, timezone


class RateLimitExceeded(Exception):
    """Raised while an acquired slot is missing; carries Retry-After seconds."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            f"run request rejected by limiter; retry after {retry_after_seconds}s"
        )
        self.retry_after_seconds = retry_after_seconds


class RunLimiter:
    def __init__(self, *, min_gap_seconds: float = 30.0, max_per_day: int = 50) -> None:
        self._min_gap = max(0.0, float(min_gap_seconds))
        self._max_per_day = max(0, int(max_per_day))
        self._lock = threading.Lock()
        self._in_flight = False
        self._last_start: float | None = None
        self._day: str = ""
        self._used_today: int = 0

    @classmethod
    def from_env(cls) -> "RunLimiter":
        def _num(name: str, default: float, minimum: float, maximum: float) -> float:
            try:
                raw = os.environ.get(
                    name,
                    str(int(default)) if float(default).is_integer() else str(default),
                )
                val = float(raw or default)
            except ValueError:
                val = default
            return min(maximum, max(minimum, val))

        gap = _num("RUN_MIN_GAP_SECONDS", 30.0, 0.0, 3600.0)
        per_day = _num("RUNS_PER_DAY", 50.0, 0.0, 100000.0)
        return cls(min_gap_seconds=gap, max_per_day=int(per_day))

    def describe(self) -> str:
        return (
            f"RunLimiter(min_gap={self._min_gap:.0f}s, max_per_day="
            f"{'off' if self._max_per_day == 0 else self._max_per_day})"
        )

    def acquire(self) -> None:
        """Acquire a run slot or raise RateLimitExceeded (no sleeping here)."""
        with self._lock:
            if self._in_flight:
                raise RateLimitExceeded(max(1, int(self._min_gap) or 15))
            now = time.time()
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if today != self._day:
                self._day = today
                self._used_today = 0
            if 0 < self._max_per_day <= self._used_today:
                # Retry after the top of the next UTC day, capped to 6h.
                seconds_until_utc_midnight = int(
                    (
                        datetime(
                            *[int(p) for p in today.split("-")],
                            hour=0, minute=0, second=0, tzinfo=timezone.utc,
                        ).timestamp()
                        + 86400
                    )
                    - now
                )
                raise RateLimitExceeded(
                    max(1, min(seconds_until_utc_midnight, 3600 * 6))
                )
            if self._last_start is not None and self._min_gap > 0:
                remaining = self._min_gap - (now - self._last_start)
                if remaining > 0:
                    raise RateLimitExceeded(max(1, int(remaining) + 1))
            self._last_start = now
            self._used_today += 1
            self._in_flight = True

    def release(self) -> None:
        with self._lock:
            self._in_flight = False

    @property
    def used_today(self) -> int:
        with self._lock:
            return self._used_today


_LIMITER: RunLimiter | None = None
_SUGGEST_LIMITER: RunLimiter | None = None
_LIMITER_LOCK = threading.Lock()


def get_run_limiter() -> RunLimiter:
    """Process-global limiter (dev/demo: single uvicorn process)."""
    global _LIMITER
    with _LIMITER_LOCK:
        if _LIMITER is None:
            _LIMITER = RunLimiter.from_env()
        return _LIMITER


def suggest_limiter_from_env() -> RunLimiter:
    """The suggester spends from the SAME free-model budget as runs (the
    suggest endpoint is open to repeated clicks, so it needs its own cap):
    no gap (one short call at a time is harmless), a day cap of its own."""
    raw = os.environ.get("SUGGESTS_PER_DAY", "30")
    try:
        per_day = int(float(raw))
    except ValueError:
        per_day = 30
    return RunLimiter(min_gap_seconds=0.0, max_per_day=per_day)


def get_suggest_limiter() -> RunLimiter:
    global _SUGGEST_LIMITER
    with _LIMITER_LOCK:
        if _SUGGEST_LIMITER is None:
            _SUGGEST_LIMITER = suggest_limiter_from_env()
        return _SUGGEST_LIMITER


def reset_run_limiter() -> None:
    """Test hook: drop the global instances (never used in production paths)."""
    global _LIMITER, _SUGGEST_LIMITER
    with _LIMITER_LOCK:
        _LIMITER = None
        _SUGGEST_LIMITER = None


__all__ = [
    "RateLimitExceeded",
    "RunLimiter",
    "get_run_limiter",
    "get_suggest_limiter",
    "suggest_limiter_from_env",
    "reset_run_limiter",
]
