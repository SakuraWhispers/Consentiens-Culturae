"""Live Qloo HTTP client (docs/architecture.md section 8).

HTTP only: builds requests, applies timeout + retry policy, returns a typed
response or raises a typed error. Knows nothing about decisions, scores, or
evidence schemas — mapping lives in qloo_adapter / evidence_normalizer.

Policy (docs/qloo-api-notes.md sections 4–5, SCOPE.md section 3):
  max 10 calls per run (enforced by the coordinator, not here),
  10 s timeout per call, 1 retry on 429 (respecting Retry-After) and on 5xx.
  401/403: no retry. Request bodies, headers, and keys never enter logs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class QlooResponse:
    endpoint: str
    http_status: int
    body: dict[str, Any]
    params_redacted: dict[str, str]


@dataclass(frozen=True)
class QlooError(Exception):
    code: str  # one of app.schemas.evidence.ErrorCode
    http_status: int | None
    message_safe: str | None = None


_REDACTED = "<redacted>"


class QlooClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 10.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._timeout = timeout_seconds
        self._client = http_client or httpx.Client(timeout=timeout_seconds)

    def get(self, path: str, params: dict[str, str]) -> QlooResponse:
        url = self._base + path
        attempts = 0
        while True:
            attempts += 1
            try:
                resp = self._client.get(url, params=params, headers={"X-Api-Key": self._key})
            except httpx.TimeoutException:
                raise QlooError("QLOO_TIMEOUT", None, f"GET {path} timed out") from None
            except httpx.RequestError as exc:
                raise QlooError("QLOO_UPSTREAM_ERROR", None, f"GET {path}: {type(exc).__name__}") from None

            if resp.status_code in (401, 403):
                raise QlooError("QLOO_AUTH_FAILED", resp.status_code, "Qloo rejected the key")
            if resp.status_code == 429 and attempts < 2:
                time.sleep(_retry_after(resp))
                continue
            if resp.status_code == 429:
                raise QlooError("QLOO_RATE_LIMITED", 429, "Qloo rate limit; retry later")
            if 500 <= resp.status_code < 600 and attempts < 2:
                time.sleep(2.0)
                continue
            if 500 <= resp.status_code < 600:
                raise QlooError("QLOO_UPSTREAM_ERROR", resp.status_code, "Qloo upstream error")
            if resp.status_code == 400:
                raise QlooError(
                    "QLOO_MALFORMED_RESPONSE", 400, _safe_error_text(resp) or "Qloo rejected the parameters"
                )
            body = _parse_json(resp, path)
            return QlooResponse(
                endpoint=path,
                http_status=resp.status_code,
                body=body,
                params_redacted=dict(params),
            )


def _retry_after(resp: httpx.Response) -> float:
    try:
        return max(0.0, min(60.0, float(resp.headers.get("Retry-After", "1"))))
    except (TypeError, ValueError):
        return 1.0


def _parse_json(resp: httpx.Response, path: str) -> dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        raise QlooError(
            "QLOO_MALFORMED_RESPONSE", resp.status_code, f"GET {path}: non-JSON response"
        ) from None
    if not isinstance(body, dict):
        raise QlooError(
            "QLOO_MALFORMED_RESPONSE", resp.status_code, f"GET {path}: response was not an object"
        )
    return body


def _safe_error_text(resp: httpx.Response) -> str | None:
    """First error message only, truncated. Never headers, params, or keys."""
    try:
        body = resp.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            msg = errors[0].get("message")
            if isinstance(msg, str):
                return msg[:300]
    return None


__all__ = ["QlooClient", "QlooError", "QlooResponse"]
