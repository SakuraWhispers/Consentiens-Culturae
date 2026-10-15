# scripts/qloo_smoke_test.py — the G1 API spike (AGENTS.md section 7).

# Run MANUALLY with a real key: QLOO_API_KEY=... python scripts/qloo_smoke_test.py
# Makes one authenticated call per allowlisted-candidate endpoint, parses the
# response into internal objects, and optionally saves a REDACTED fixture.

# Hard rules honored here:
# - the key is read from the environment only, never printed, never saved
# - no key or header value ever lands in a fixture or in stdout
# - everything is recorded later by hand in docs/qloo-api-notes.md

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    print("httpx not installed. Run: pip install -e '.[dev]'")
    sys.exit(1)

TIMEOUT_SECONDS = 10.0

# Lead candidates from docs/qloo-api-notes.md (status: UNVERIFIED).
# The script tries both base URLs and records which one authenticates.
BASE_URL_CANDIDATES = [
    "https://hackathon.api.qloo.com",
    "https://api.qloo.com",
]

ENDPOINT_CANDIDATES = [
    ("search", "/search", {"query": "{term}"}),
    ("tags", "/v2/tags", {"query": "{term}"}),
    ("insights", "/v2/insights", {"query": "{term}"}),
]

REDACTION_KEYS = {"api_key", "key", "token", "secret", "authorization", "x-api-key"}


def redact(obj: Any) -> Any:
    """Strip anything key-shaped, recursively. Keys or values that look like secrets."""
    if isinstance(obj, dict):
        return {
            k: ("<redacted>" if str(k).lower() in REDACTION_KEYS else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(item) for item in obj]
    return obj


def looks_like_secret(value: str) -> bool:
    lowered = value.lower()
    return "key" in lowered or "token" in lowered


def try_endpoint(client: httpx.Client, base_url: str, path: str, params: dict[str, str], api_key: str) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    try:
        resp = client.get(url, params=params, headers={"X-Api-Key": api_key})
    except httpx.TimeoutException:
        return {"status": "timeout", "seconds": TIMEOUT_SECONDS}
    except httpx.RequestError as exc:
        # never include the URL query string in the message; it can carry params
        return {"status": "request_error", "type": type(exc).__name__}

    body: Any = None
    try:
        body = resp.json()
    except ValueError:
        return {
            "status": "non_json",
            "http_status": resp.status_code,
            "content_type": resp.headers.get("content-type"),
            "body_length": len(resp.content),
        }
    return {
        "status": "ok" if resp.is_success else "http_error",
        "http_status": resp.status_code,
        "json": body,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Qloo G1 API spike (manual, offline-safe)")
    parser.add_argument("--term", default="stationery", help="search term for the spike")
    parser.add_argument(
        "--save-fixture",
        metavar="PATH",
        help='save the first SUCCESSFUL response as a redacted fixture (adds the _meta block)',
    )
    args = parser.parse_args()

    api_key = os.environ.get("QLOO_API_KEY")
    if not api_key:
        print("QLOO_API_KEY is not set. Export it and rerun. (No secrets are ever echoed.)")
        return 2

    print("G1 spike: probing base URLs and endpoints. Results are printed WITHOUT the key.")
    print(f"term: {args.term!r}  timeout: {TIMEOUT_SECONDS}s\n")

    saved: dict[str, Any] | None = None
    results: list[dict[str, Any]] = []

    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        for base_url in BASE_URL_CANDIDATES:
            for name, path, params in ENDPOINT_CANDIDATES:
                filled = {k: v.replace("{term}", args.term) for k, v in params.items()}
                started = time.monotonic()
                outcome = try_endpoint(client, base_url, path, filled, api_key)
                elapsed = round(time.monotonic() - started, 2)
                label = f"{base_url}{path}"
                http_status = outcome.get("http_status") if isinstance(outcome, dict) else None
                print(f"[{name}] {label} -> {outcome.get('status')} (http {http_status}) in {elapsed}s")
                if isinstance(outcome.get("json"), dict):
                    top_keys = sorted(outcome["json"].keys())
                    print(f"    top-level keys: {top_keys}")
                results.append({"endpoint": label, "outcome": outcome})
                if (
                    saved is None
                    and outcome.get("status") == "ok"
                    and isinstance(outcome.get("json"), dict)
                ):
                    saved = {"endpoint": label, "body": outcome["json"], "params": filled}
            # stop early once one base URL authenticated successfully
            if any(r["outcome"].get("http_status") == 200 for r in results if r["endpoint"].startswith(base_url)):
                print(f"\nBase URL that authenticated: {base_url}")
                break

    authenticated = [
        r for r in results if r["outcome"].get("http_status") == 200
    ]
    print("\nSummary:")
    print(f"  successful (200) calls: {len(authenticated)}")
    for r in authenticated:
        print(f"    {r['endpoint']}")
    if not authenticated:
        print(
            "  No endpoint returned 200. Record what did happen in docs/qloo-api-notes.md "
            "before building anything on this API."
        )

    if args.save_fixture:
        if not saved:
            print("No successful response to save; fixture not written.")
        else:
            fixture = {
                "_meta": {
                    "fixture": True,
                    "source": "recorded",
                    "recorded_at": time.strftime("%Y-%m-%d"),
                    "redacted": True,
                    "endpoint": saved["endpoint"],
                },
                "request_params": redact(saved["params"]),
                "response": redact(saved["body"]),
            }
            with open(args.save_fixture, "w", encoding="utf-8") as fh:
                json.dump(fixture, fh, indent=2, ensure_ascii=False)
            print(f"Saved redacted fixture to {args.save_fixture} (verify no secrets inside before committing).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
