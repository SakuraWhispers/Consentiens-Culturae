"""Unit tests for the run limiter (protects the free-model budget)."""

import pytest

from app.services.rate_limiter import RateLimitExceeded, RunLimiter, reset_run_limiter


def test_first_run_succeeds_then_gap_blocks() -> None:
    limiter = RunLimiter(min_gap_seconds=30, max_per_day=50)
    limiter.acquire()
    limiter.release()
    with pytest.raises(RateLimitExceeded, match="retry after"):
        limiter.acquire()
    limiter.release()


def test_retrying_after_gap_succeeds(monkeypatch) -> None:
    limiter = RunLimiter(min_gap_seconds=30, max_per_day=50)
    later = 61.0
    monkeypatch.setattr("app.services.rate_limiter.time.time", lambda: later)
    limiter.acquire()
    limiter.release()
    monkeypatch.setattr("app.services.rate_limiter.time.time", lambda: later + 31.0)
    limiter.acquire()
    limiter.release()


def test_daily_cap_blocks_with_long_retry() -> None:
    limiter = RunLimiter(min_gap_seconds=0, max_per_day=2)
    for _ in range(2):
        limiter.acquire()
        limiter.release()
    with pytest.raises(RateLimitExceeded):
        limiter.acquire()


def test_zero_daily_cap_disables_day_limit() -> None:
    limiter = RunLimiter(min_gap_seconds=0, max_per_day=0)
    for _ in range(3):
        limiter.acquire()
        limiter.release()


def test_concurrent_run_rejected_until_first_finishes() -> None:
    limiter = RunLimiter(min_gap_seconds=0, max_per_day=0)
    limiter.acquire()
    with pytest.raises(RateLimitExceeded):
        limiter.acquire()
    limiter.release()
    limiter.acquire()
    limiter.release()


def test_used_today_counts_attempts() -> None:
    limiter = RunLimiter(min_gap_seconds=0, max_per_day=10)
    limiter.acquire()
    limiter.release()
    assert limiter.used_today == 1


def test_reset_run_limiter_drops_global(monkeypatch) -> None:
    from app.services import rate_limiter as rl

    reset_run_limiter()
    a = rl.get_run_limiter()
    reset_run_limiter()
    b = rl.get_run_limiter()
    assert a is not b
    reset_run_limiter()


def test_suggest_limiter_has_its_own_day_cap(monkeypatch) -> None:
    from app.services import rate_limiter as rl

    monkeypatch.setenv("SUGGESTS_PER_DAY", "2")
    reset_run_limiter()
    suggest = rl.get_suggest_limiter()
    for _ in range(2):
        suggest.acquire()
        suggest.release()
    with pytest.raises(RateLimitExceeded):
        suggest.acquire()
    reset_run_limiter()


def test_suggest_limiter_does_not_consume_run_slots() -> None:
    from app.services import rate_limiter as rl

    reset_run_limiter()
    suggest = rl.get_suggest_limiter()
    suggest.acquire()  # a suggester call is in flight
    run = rl.get_run_limiter()
    run.acquire()  # ...and the run limiter must not feel it
    run.release()
    suggest.release()
    reset_run_limiter()
