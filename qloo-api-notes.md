# qloo-api-notes.md — What we know about the Qloo API, and how we know it

**Rule for this file:** a fact is either **VERIFIED** (we made a real call, recorded the date and the redacted response fixture) or **UNVERIFIED** (someone said it, a doc said it, a third-party project said it, but we have not confirmed it ourselves). Agents may only build live calls against VERIFIED entries. UNVERIFIED entries are hypotheses to test at G1.

Do not copy keys, tokens, or full account details into this file.

Last updated: 2026-10-15. Current verification status: **nothing verified yet. G1 is open.**

---

## 1. Access and sources

| Item | Status | Notes |
|---|---|---|
| Hackathon API key | UNVERIFIED — not obtained | Requested through the Google Form linked from the Qloo Devpost resources page. Key is per person; do not share it. |
| Starter kit | UNVERIFIED — not read | https://github.com/qloo/qloo-hackathon-kit (read it at G1; record anything it says about endpoints here) |
| Official API guide | UNVERIFIED — not read | https://docs.qloo.com/reference/qloo-llm-hackathon-developer-guide. At 2026-10-15 this page blocks automated fetching (robots.txt). Read it in a browser, by hand, and record the findings here. |
| Hackathon Discord | UNVERIFIED — not consulted | https://discord.gg/rF9PKsD5Q7 — ask questions about endpoint access there and record answers with dates. |
| Devpost rules | VERIFIED 2026-10-15 (read via web fetch) | https://qloo.devpost.com/rules. Re-read before submission; rules can change. See §8. |

---

## 2. Base URL and authentication

| Item | Status | Value / source |
|---|---|---|
| Base URL for hackathon access | UNVERIFIED | A third-party hackathon project reports `https://hackathon.api.qloo.com`. Treat as a lead only. Confirm against the official guide. |
| Auth header | UNVERIFIED | A third-party project reports the key is sent as an `X-Api-Key` header. Confirm. |
| Key storage | RULE | Environment variable `QLOO_API_KEY` only. Never in code, fixtures, logs, or the frontend. |
| Behavior on bad key | UNVERIFIED | Expect 401 or 403. Confirm which, and the response body shape. |

---

## 3. Endpoints

**Allowlist rule:** the app may call only endpoints marked VERIFIED below. The researcher agent's tool catalogue is generated from this table. Any endpoint not in this table is not callable.

| Purpose | Endpoint (as reported) | Status | Verified by | Notes |
|---|---|---|---|---|
| Resolve entity names to Qloo entity IDs | `GET /search` (reported) | UNVERIFIED | — | Third-party projects describe this as resolving names across entity types (artists, books, brands, destinations, movies, people, places, podcasts, TV shows, video games). Test which entity types the key can use. |
| Resolve tags (genre, style, keywords) to tag IDs | `GET /v2/tags` (reported) | UNVERIFIED | — | Reported in third-party projects. |
| Taste-based recommendations for one entity type | `GET /v2/insights` (reported) | UNVERIFIED | — | Reported to take entity, tag, audience, and location signals. Test what filters are accepted. |
| Affinity by demographic (age, gender) | `GET /v2/insights` with `urn:demographics` (reported) | UNVERIFIED — **do not use as a scored input** (see SCOPE.md §4) | — | Included only so we know it exists. The app may not use it for scoring. |
| Tags describing the taste of an entity set, audience, or location | `GET /v2/insights` with `urn:tag` (reported) | UNVERIFIED | — | Candidate for C1 and C3 evidence. |

**Things we must learn at G1 for each endpoint:**
- Is it available to the hackathon key at all?
- Required and optional parameters, exact names.
- Which entity types and tag IDs are valid for "stationery," "creative accessories," "gift," and the chosen city or market.
- Response shape: top-level keys, entity list field names, ID field names, score or affinity field names, pagination fields.
- Whether the response includes an affinity value on a fixed scale (and what the scale is), or only a ranked order. This determines the normalization method in `architecture.md` §3.1.
- Empty-result shape, and whether "no results" is distinguishable from "error."

---

## 4. Rate limits and quotas

| Item | Status | Notes |
|---|---|---|
| Requests per second | UNVERIFIED | Unknown. Watch for 429 responses and any `Retry-After` header. |
| Daily or total quota | UNVERIFIED | Unknown. Check the dashboard if one exists; record the number here. |
| Per-request result limits | UNVERIFIED | Check for a `limit` parameter and its maximum. |

Until verified, the app assumes: 1 request per second per run, max 10 calls per run, max 1 retry on 429.

---

## 5. Error handling we must implement (independent of what Qloo actually returns)

| Condition | Required behavior |
|---|---|
| 401 / 403 | Stop calling Qloo for this run. Record `QLOO_AUTH_FAILED`. Report: "Qloo rejected the key; live evidence unavailable." |
| 429 | One retry with backoff (respect `Retry-After` if present). If still 429, record `QLOO_RATE_LIMITED`. |
| 5xx | One retry after 2 seconds. Then record `QLOO_UPSTREAM_ERROR`. |
| Timeout (10 s) | Record `QLOO_TIMEOUT`. Do not retry more than once. |
| Malformed JSON | Record `QLOO_MALFORMED_RESPONSE` with response length only. Never log the body. |
| Valid response, zero matches | Record `QLOO_NO_MATCH`, `coverage_status=missing`. Never convert to a low score. |
| Unexpected extra fields | Ignore unknown fields; log field names (not values) as a warning. |
| Missing expected field | Record `coverage_status=partial` with the field name in `limitations`. |

---

## 6. Fixtures

**Policy:**
- Fixtures are saved from real responses only after redaction (no keys, no account IDs, no headers).
- Every fixture file is named `fixture_<endpoint>_<scenario>.json`, and carries a `_meta` block: `{"fixture": true, "source": "recorded|hand-written", "recorded_at": "YYYY-MM-DD", "redacted": true}`.
- **Hand-written fixtures** must be shaped like the verified schema and must say `"source": "hand-written"`. They are used only for adversarial cases (timeout, 429, malformed, ambiguous match). They must never be presented as live output.
- The UI and report show a fixture banner whenever any evidence record has `fixture_mode=true`.

**Fixtures to create after G1:**
- `fixture_search_success.json` (recorded)
- `fixture_insights_success.json` (recorded)
- `fixture_tags_success.json` (recorded)
- `fixture_no_match.json` (recorded if it occurs, otherwise hand-written)
- `fixture_adv_ambiguous_match.json` (hand-written)
- `fixture_adv_rate_limited.json` (hand-written; represents 429)
- `fixture_adv_malformed.json` (hand-written)
- `fixture_adv_missing_field.json` (hand-written)

---

## 7. Qloo terms that constrain what we store and show

Status: **UNVERIFIED.** Read Qloo's API terms and the hackathon terms before G5. Record here:

- [ ] Can we store raw responses? For how long?
- [ ] Can we display Qloo entity names and affinity values in a public demo?
- [ ] Attribution requirements (text or logo)?
- [ ] Any restriction on caching or on combining with other data?
- [ ] Any restriction on use in a commercial or post-hackathon product?
- [ ] Any restriction on use with an LLM (sending Qloo output to a model provider)?

**Until these are checked:** store only what reproducibility needs (IDs, normalized values, match quality, timestamps). Do not store full raw payloads in the public demo database. Do not send raw Qloo payloads to the LLM; send normalized summaries only.

---

## 8. Hackathon rules that interact with the API

VERIFIED 2026-10-15 from https://qloo.devpost.com/rules:

- Project must integrate the Qloo API and must either function as an agentic tool, be built with an agent framework, or integrate Qloo into an existing agent.
- Stage One is pass/fail: the project must reasonably apply the required APIs/SDKs.
- Project must run as shown in the demo and must be testable by judges until the judging period ends (Nov 16).
- Third-party SDKs and data must be used under their terms.
- Public repository with an open-source license file, visible in the About section.

Implication: the Qloo integration is not optional decoration. The demo must visibly use Qloo output in the scoring path.

---

## 9. Verification log

Append-only. One line per verification. Format: `YYYY-MM-DD | what was checked | how | result | fixture file (if any)`

- 2026-10-15 | Devpost rules and resources page | web fetch | rules and deadline confirmed; resources page links to starter kit and key form | none
- 2026-10-15 | Official Qloo hackathon developer guide | web fetch | blocked by robots.txt; not read | none
- 2026-10-15 | Endpoint names and auth header | web search of third-party hackathon projects | reported only; **not verified** | none

---

## 10. Open questions for G1 (answer each, with date)

1. Which endpoints does the hackathon key allow? (Test each one listed in §3.)
2. What is the exact base URL and auth header?
3. What is the rate limit, and what does a 429 look like?
4. Does the affinity signal come as a numeric scale, or only as a ranked list?
5. Can a query be restricted to a city or market? If not, how is "market" represented?
6. What are valid entity types and tag IDs for stationery and creative accessories?
7. What does a no-match response look like?
8. What is the response size for a typical call? (Affects fixture size and latency.)
9. Does the starter kit contain a client or schema we should reuse? (Reuse only if it fits the adapter boundary.)
