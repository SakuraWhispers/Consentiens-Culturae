"""Qloo adapter boundary (docs/architecture.md section 8).

v0.1 contains only the FixtureSource. The live HTTP client
(`integrations/qloo_client.py`) arrives at G1 with a real key; the adapter
protocol below shows what it must satisfy. This module is the only place that
knows about fixture file layout; the normalizer knows only payload shapes.

Fixture policy (SCOPE.md decision log 2026-10-16): only hand-written,
synthetic fixtures are committed. Recorded live responses would live in the
gitignored tests/fixtures/recorded/ and never enter the public repo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


class QlooPayload(BaseModel):
    """What an evidence source returns BEFORE normalization."""

    endpoint: str
    query_params_redacted: dict[str, str] = {}
    payload: dict[str, Any]
    source: str  # "fixture" or "qloo"
    fixture_mode: bool


class EvidenceSource(Protocol):
    def load(self, endpoint: str, params: dict[str, str]) -> QlooPayload: ...


class FixtureError(RuntimeError):
    """Fixture file is missing, unlabeled, or was labeled 'recorded'."""


def load_fixture_file(path: Path) -> dict[str, Any]:
    """Validate the fixture envelope and return its inner payload.

    Requires the `_meta` block (docs/qloo-api-notes.md section 6). Synthetic
    (hand-written) fixtures are expected; `recorded` source is REJECTED here so
    a recording can never be mistaken for synthetic data.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FixtureError(f"fixture not readable: {path.name}") from exc
    except ValueError as exc:
        raise FixtureError(f"fixture is not valid JSON: {path.name}") from exc

    meta = raw.get("_meta")
    if not isinstance(meta, dict) or meta.get("fixture") is not True:
        raise FixtureError(f"fixture missing labelled _meta block: {path.name}")
    if meta.get("source") == "recorded":
        raise FixtureError(
            f"recorded fixture {path.name} refused by synthetic loader; "
            "recorded responses must live in tests/fixtures/recorded/ (gitignored)"
        )
    if not isinstance(raw.get("response"), dict):
        raise FixtureError(f"fixture lacks a response object: {path.name}")

    return raw


class FixtureSource:
    """Serves pre-approved synthetic fixture payloads (offline everywhere)."""

    is_live = False

    def __init__(self, fixtures_dir: Path = FIXTURES_DIR) -> None:
        self._dir = fixtures_dir

    def load(self, endpoint: str, params: dict[str, str]) -> QlooPayload:
        filename = self._fixture_for(endpoint)
        path = self._dir / filename
        raw = load_fixture_file(path)
        return QlooPayload(
            endpoint=endpoint,
            query_params_redacted=dict(params),
            payload=raw["response"],
            source="fixture",
            fixture_mode=True,
        )

    @staticmethod
    def _fixture_for(endpoint: str) -> str:
        mapping = {
            "search": "fixture_search_synthetic_success.json",
            "insights": "fixture_insights_synthetic_success.json",
        }
        try:
            return mapping[endpoint]
        except KeyError:
            raise FixtureError(f"no synthetic fixture mapped for endpoint {endpoint!r}") from None


__all__ = ["QlooPayload", "EvidenceSource", "FixtureSource", "FixtureError", "load_fixture_file"]


class LiveEvidenceSource:
    """Live Qloo calls behind the EvidenceSource protocol (G1 VERIFIED shapes).

    Allowlist: "search" and "insights" only. Anything else raises ValueError
    before any network call. QlooError propagates to the coordinator, which
    turns it into an error record (never an empty result, never a score).
    """

    is_live = True

    _PATHS = {"search": "/search", "insights": "/v2/insights"}

    def __init__(self, client: Any, tag_urn: str | None = None) -> None:
        self._client = client
        self.tag_urn = tag_urn
        self.calls_made = 0

    def load(self, endpoint: str, params: dict[str, str]) -> QlooPayload:
        if endpoint not in self._PATHS:
            raise ValueError(f"endpoint {endpoint!r} is not on the Qloo allowlist")
        self.calls_made += 1
        resp = self._client.get(self._PATHS[endpoint], params)
        return QlooPayload(
            endpoint=endpoint,
            query_params_redacted=dict(params),
            payload=resp.body,
            source="qloo",
            fixture_mode=False,
        )
