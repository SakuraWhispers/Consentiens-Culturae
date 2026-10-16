"""qloo_client tests: httpx MockTransport, offline. No network, no secrets."""

from __future__ import annotations

import json

import httpx
import pytest

from app.integrations.qloo_client import QlooClient, QlooError


def _client(handler, **kw):
    transport = httpx.MockTransport(handler)
    return QlooClient(
        base_url="https://hackathon.api.qloo.com",
        api_key="test-key-never-real",
        http_client=httpx.Client(transport=transport, timeout=10.0),
        **kw,
    )


def _json_response(status: int, body: dict, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body).encode(), headers=headers or {})


def test_success_returns_typed_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Api-Key"] == "test-key-never-real"
        assert request.method == "GET"
        return _json_response(200, {"success": True, "results": []})

    resp = _client(handler).get("/search", {"query": "x"})
    assert resp.http_status == 200
    assert resp.body == {"success": True, "results": []}


def test_401_maps_to_auth_failed_no_retry() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _json_response(401, {"error": {"message": "Unauthorized"}})

    with pytest.raises(QlooError) as exc:
        _client(handler).get("/search", {"query": "x"})
    assert exc.value.code == "QLOO_AUTH_FAILED"
    assert len(calls) == 1


def test_429_retries_once_then_rate_limited() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _json_response(429, {"error": "slow down"}, {"Retry-After": "0"})

    with pytest.raises(QlooError) as exc:
        _client(handler).get("/search", {"query": "x"})
    assert exc.value.code == "QLOO_RATE_LIMITED"
    assert len(calls) == 2


def test_429_recovers_on_retry() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return _json_response(429, {}, {"Retry-After": "0"})
        return _json_response(200, {"success": True})

    resp = _client(handler).get("/search", {"query": "x"})
    assert resp.http_status == 200
    assert len(calls) == 2


def test_400_maps_to_malformed_with_safe_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(400, {"errors": [{"message": "bad param"}]})

    with pytest.raises(QlooError) as exc:
        _client(handler).get("/v2/insights", {"filter.type": "urn:entity:brand"})
    assert exc.value.code == "QLOO_MALFORMED_RESPONSE"
    assert "bad param" in (exc.value.message_safe or "")


def test_5xx_retries_once_then_upstream_error() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _json_response(503, {"error": "down"})

    with pytest.raises(QlooError) as exc:
        _client(handler).get("/search", {"query": "x"})
    assert exc.value.code == "QLOO_UPSTREAM_ERROR"
    assert len(calls) == 2


def test_timeout_maps_to_qloo_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(QlooError) as exc:
        _client(handler).get("/search", {"query": "x"})
    assert exc.value.code == "QLOO_TIMEOUT"


def test_non_json_maps_to_malformed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>")

    with pytest.raises(QlooError) as exc:
        _client(handler).get("/search", {"query": "x"})
    assert exc.value.code == "QLOO_MALFORMED_RESPONSE"
