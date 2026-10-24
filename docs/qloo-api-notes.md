# qloo-api-notes.md — What we know about the Qloo API, and how we know it

**Rule for this file:** a fact is either **VERIFIED** (we made a real call, recorded the date and the redacted response fixture) or **UNVERIFIED** (someone said it, a doc said it, a third-party project said it, but we have not confirmed it ourselves). Agents may only build live calls against VERIFIED entries. UNVERIFIED entries are hypotheses to test at G1.

Do not copy keys, tokens, or full account details into this file.

Last updated: 2026-10-16. Current verification status: **endpoint facts DOCS-VERIFIED from the official developer guide (fetched 2026-10-16); no live call made yet. G1 is open.**

---

## 0. Status labels used in this file

- **VERIFIED** — we made a real call ourselves and recorded a redacted fixture. Nothing is at this level yet.
- **DOCS-VERIFIED** — taken verbatim from an official Qloo page we fetched ourselves, with the date and URL. Reliable for design; each still needs one live confirmation at G1 before the live path depends on it.
- **UNVERIFIED** — a lead only. Never build on this directly.

---

## 1. Access and sources

| Item | Status | Notes |
|---|---|---|
| Hackathon API key | UNVERIFIED — not obtained | Requested through the Google Form linked from the Qloo Devpost resources page. Key is per person; do not share it. |
| Starter kit | UNVERIFIED — not read | https://github.com/qloo/qloo-hackathon-kit. 2026-10-16: github.com is not fetchable from the dev host (DNS-restricted); web search describes it as "Starter kit for building taste-powered hackathon projects with Qloo's public CLI and MCP", with a companion repo holding Qloo's public API docs and OpenAPI spec. Human will clone it locally when possible; read at G1. |
| Official API guide | DOCS-VERIFIED 2026-10-16 | https://docs.qloo.com/reference/qloo-llm-hackathon-developer-guide — the 2026-10-15 robots.txt block no longer applied; page fetched in full and findings recorded throughout this file. |
| Hackathon Discord | UNVERIFIED — not consulted | https://discord.gg/rF9PKsD5Q7 — ask questions about endpoint access there and record answers with dates. |
| Devpost rules | VERIFIED 2026-10-15 (read via web fetch) | https://qloo.devpost.com/rules. Re-read before submission; rules can change. See §8. |

---

## 2. Base URL and authentication

| Item | Status | Value / source |
|---|---|---|
| Base URL for hackathon access | DOCS-VERIFIED 2026-10-16 | `https://hackathon.api.qloo.com` — the ONLY base URL the hackathon key works against. Staging (`staging.api.qloo.com`) and production (`api.qloo.com`) always return 401 with a hackathon key, even if the key is valid. |
| Auth header | DOCS-VERIFIED 2026-10-16 | `X-Api-Key` request header. Not a query parameter, not `Authorization: Bearer`. Missing header → 401 "No API key found in request". |
| Key storage | RULE | Environment variable `QLOO_API_KEY` only. Never in code, fixtures, logs, or the frontend. |
| Behavior on bad key | DOCS-VERIFIED 2026-10-16 | 401 for missing header, invalid key, or correct key against the wrong base URL. Distinguish the three by checking base URL and header first. (Response body shape: confirm at G1.) |
| Insights HTTP method | DOCS-VERIFIED 2026-10-16 | `/v2/insights` is a **GET**; all parameters go in the query string. A POST with a JSON body fails (404 / "No path matching request parameters") even with correct parameters. |
| Response field filtering | DOCS-VERIFIED 2026-10-16 | Not supported. The API returns the full response (including verbose fields like `akas`); no way to suppress fields server-side. We extract client-side. |

---

## 3. Endpoints

**Allowlist rule:** the app may call only endpoints marked **DOCS-VERIFIED** or **VERIFIED** below. The researcher agent's tool catalogue is generated from this table. Any endpoint not in this table is not callable. Endpoint rows stay at DOCS-VERIFIED until one real authenticated call (G1) upgrades them to VERIFIED.

| Purpose | Endpoint (as documented) | Status | Verified by | Notes |
|---|---|---|---|---|
| Resolve entity names to Qloo entity IDs | `GET /search` | VERIFIED 2026-10-16 (live) | G1 spike, `?query=stationery/Moleskine/LEGO/New York` → 200 | `results` is a LIST (not `results.entities`); 20 hits per call; entity keys `disambiguation, entity_id, location?, name, popularity (top-level 0–1 float), properties, tags, types[]`. `type/subtype` top-level ABSENT on /search hits (present on insights hits). Tags use `tag_id`/`value`, not `id`. Normalizer update required (G2). |
| Resolve tags (genre, style, keywords) to tag IDs | `GET /v2/tags` (Tags Search API) | VERIFIED 2026-10-16 (live) | G1 spike, `?filter.query=stationery` → 200 | Correct param is `filter.query`, NOT `query` (`query` → 400 with `errors[].message` listing valid params). Shape: `results.tags[]` with `id/name/type/parents/popularity`. Hit: `urn:tag:category:place:stationery_store`. |
| Taste-based recommendations for one entity type | `GET /v2/insights` | VERIFIED 2026-10-16 (live) | G1 spike, `filter.type=urn:entity:place + filter.tags=<stationery_store URN>` → 200, 20 entities | `filter.type` alone → 400 `at least one valid signal or filter is required`. Valid combo: `filter.tags` with a `/v2/tags`-resolved URN. Shape: `success/results.entities[]` (matches docs). `urn:entity:brand` + same tag → 200 with 0 entities (genuine no-match). One `signal.interests.tags` call timed out (QLOO_TIMEOUT observed, retry policy justified). |
| Affinity by demographic (age, gender) | `GET /v2/insights` with demographic signals | DOCS-VERIFIED 2026-10-16 | official hackathon guide | **do not use as a scored input** (see SCOPE.md §4). `signal.demographics.audiences` requires audience URN values, not freeform strings. Included only so we know it exists. |
| Tags describing the taste of an entity set, audience, or location | `GET /v2/insights` with tag/entity signals ("Taste Analysis") | DOCS-VERIFIED 2026-10-16 | official hackathon guide | Taste Analysis is a usage mode of the Insights API, not a separate endpoint. Candidate for C1 and C3 evidence. |
| Legacy recommendations | `/recs`, `/recommendations` | FORBIDDEN | official hackathon guide | Do not call, not even as an experiment: "Do not use /recommendations or /recs. These are legacy endpoints and are not supported for the hackathon." |
| Compare two entity groups | `Analysis Compare` | DOCS-VERIFIED (name) | API overview page | Exact path/params unknown; not needed for v1. Record only. |
| Popularity over time | `Get Trending Data` | DOCS-VERIFIED (name) | API overview page | Exact path/params unknown; not needed for v1. Record only. |

**Behavior facts (VERIFIED 2026-10-16 live unless noted):**
- Errors are NOT silent: bad params → 400 with `errors[].message` (e.g. tags `query` → 400 listing valid `filter.*` params; insights `filter.type`-only → 400 `at least one valid signal or filter is required`). The old silent-ignore note stays DOCS-VERIFIED for other params.
- Empty-result shape (VERIFIED): 200 `{"success": true, "results": {"entities": []}}` (brand + stationery-store tag → 0 entities). Distinguishable from 400 errors by status code. No-match is NOT a negative signal.
- Entity shape correction (VERIFIED, supersedes the 2026-10-16 docs line): `/search` hits carry `popularity` TOP-LEVEL (0–1 float), `types[]` (plural), tags with `tag_id`/`value` (not `id`); `type`/`subtype` top-level absent on /search, present on insights hits. The normalizer must accept both.
- Affinity format (VERIFIED 2026-10-16): NO numeric affinity/score field observed on insights entities (checked `affin*/score/rank` keys — absent). Ranking is list order + `popularity`. Normalization implication: C1/C3 use rank-order or popularity-based min–max across the run's concepts, not a fixed affinity scale. To be finalized in architecture §3.1 at G2.
- 400 shape (VERIFIED): `{"errors": [{"message": ..., "path": ...}]}`. 401 shape (VERIFIED): `{"error": {"reason": "API keys mismatch", "message": "Unauthorized", "code": 401}}`.

**Things we must learn at G1 for each endpoint:**
- Is it available to the hackathon key at all?
- Required and optional parameters, exact names.
- Which entity types and tag IDs are valid for "stationery," "creative accessories," "gift," and the chosen city or market.
- Response shape: top-level keys, entity list field names, ID field names, score or affinity field names, pagination fields.
- Whether the response includes an affinity value on a fixed scale (and what the scale is), or only a ranked order. This determines the normalization method in `docs/architecture.md` §3.1.
- Empty-result shape, and whether "no results" is distinguishable from "error."

---

## 4. Rate limits and quotas

| Item | Status | Notes |
|---|---|---|
| Rate and quota limits | DOCS-VERIFIED (qualitative) 2026-10-16 | Hackathon keys have rate and monthly quota limits, "set high enough to support typical hackathon projects". Exact numbers NOT published. If hit, post in #api-help on Discord; limits can be raised per user. |
| Key lifetime | DOCS-VERIFIED 2026-10-16 | Keys are personal, active through the end of judging (Nov 16), deactivated after the hackathon closes. Keys are issued within ~4 hours per the Devpost FAQ (search result; confirm your own experience). |
| Per-request result limits | UNVERIFIED | Check for a `limit` parameter and its maximum at G1. |
| 429 shape | UNVERIFIED | Watch for `Retry-After` header at G1. |

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

- [x] Caching: private, server-side caching is allowed with **no time limit** (DOCS-VERIFIED 2026-10-16). Client-side/public caching of Qloo data is not — see the fixture-policy conflict below.
- [ ] Can we store raw responses? For how long? → UNKNOWN, but one hard constraint is clear: **Qloo response data must not be stored in a public repository** (DOCS-VERIFIED 2026-10-16). See the fixture-policy conflict below.
- [ ] Can we display Qloo entity names and affinity values in a public demo? (Closing this one is urgent: the report UI and the public repo are exactly that.)
- [ ] Attribution requirements (text or logo)?
- [ ] Any restriction on combining with other data?
- [ ] Any restriction on use in a commercial or post-hackathon product?
- [ ] Any restriction on use with an LLM (sending Qloo output to a model provider)?

**Fixture-policy conflict resolved (human approved 2026-10-16):** Qloo's terms forbid storing response data in a public repository; SCOPE.md planned to commit redacted recorded fixtures to `tests/fixtures/`. Resolution: **hand-written synthetic fixtures** (shaped like the verified schema, no real Qloo data) go in the public repo; **recorded live-response fixtures stay local only** in the gitignored `tests/fixtures/recorded/` directory.

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
- 2026-10-15 | Endpoint names and auth header | web search of third-party hackathon projects | reported only; not verified | none
- 2026-10-16 | Official API overview page (docs.qloo.com/reference/api-overview) | web fetch in full | Insights API structure confirmed; lookup + analysis/trends API groups listed; DOCS-VERIFIED | none
- 2026-10-16 | Official onboarding page (docs.qloo.com/reference/api-onboarding) | web fetch in full | auth header, insights example, response envelope shape (success/results.entities), GET method, field-filtering rule | none
- 2026-10-16 | Official hackathon developer guide (docs.qloo.com/reference/qloo-llm-hackathon-developer-guide) | web fetch in full | base URL, X-Api-Key, GET-only insights, filter.type required + full supported entity-type list, /search vs /v2/insights separation, /recs forbidden, silent-ignore of invalid params, empty-result shape, quota/limits and Discord escalation, caching rules, public-repo data restriction, key lifetime | none
- 2026-10-16 | Starter kit repository | web fetch + web search | github.com fetch blocked from dev host; description only via search: CLI + MCP starter kit; companion repo with OpenAPI spec | none
- 2026-10-16 | Devpost FAQ (search result qloo-hackathon.devpost.com) | web search snippet | keys issued within ~4 hours of form submission | none
- 2026-10-16 | G1 spike, first run with placeholder key | live calls via scripts/qloo_smoke_test.py | 8/8 → 401 `API keys mismatch`; confirmed auth path works, key was placeholder | none
- 2026-10-16 | G1 spike, real key: base URL + auth | live `GET /search?query=stationery` → 200 | hackathon base URL + `X-Api-Key` VERIFIED; `api.qloo.com` 401 as documented | tests/fixtures/recorded/fixture_search_live_stationery.json (LOCAL-ONLY)
- 2026-10-16 | G1 spike, real key: /search ×4, /v2/tags ×2, /v2/insights ×2 | live calls | /search 200 (20 hits each); /v2/tags 200 via `filter.query`; insights-place 200 (20 entities) via `filter.tags` URN; insights-brand 200 with 0 entities; 1 timeout on `signal.interests.tags` | tests/fixtures/recorded/fixture_tags_live_stationery.json, fixture_insights_place_stationery_store.json (LOCAL-ONLY)
- 2026-10-24 | New USAGE of already-verified endpoints (no new endpoint, no new shape claim) | code path, live contract unchanged | `/v2/tags` is now called once per LIVE run with `filter.query=<category phrase>` to resolve the run's place-category tag; the pipeline picks the most popular result whose id starts with `urn:tag:category:place:` and uses it as `filter.tags` on the shared `/v2/insights` call (`filter.type=urn:entity:place` unchanged). The resolved URN, the category phrase and the tag count are recorded in a `category_tag_resolved` (or `category_tag_unresolved`) workflow event. A model NEVER writes a URN; unresolvable => insights call skipped + limitation. Stationery-store URN remains a single 2026-10-16 resolved EXAMPLE, no longer a constant in the code | qloo-api-notes contract untouched; behavior change recorded in SCOPE.md decision log

---

## 10. Open questions for G1 (answer each, with date)

1. ~~Which endpoints does the hackathon key allow?~~ **ANSWERED 2026-10-16 (live)**: `/search`, `/v2/tags`, `/v2/insights` all 200 with the hackathon key.
2. ~~What is the exact base URL and auth header?~~ **ANSWERED 2026-10-16 (docs), VERIFIED live**: `https://hackathon.api.qloo.com` + `X-Api-Key` header.
3. What is the rate limit, and what does a 429 look like? (Numbers unpublished; no 429 observed at G1 — ~10 sequential calls fine. Stays UNVERIFIED.)
4. ~~Does the insights affinity signal come as a numeric scale, or only as a ranked list?~~ **ANSWERED 2026-10-16 (live)**: ranked list order + top-level `popularity` 0–1; no affinity/score field on entities.
5. Can a query be restricted to a city or market? (Location/geo parameters are documented in the overview; test which are valid for our entity type.)
6. ~~What are valid entity types and tag IDs for stationery and creative accessories?~~ **ANSWERED 2026-10-16 (live)**: `urn:tag:category:place:stationery_store` (+ genre variant) resolves via `filter.query=stationery`; `filter.type=urn:entity:place + filter.tags=<that URN>` → 20 hits; same tag with `urn:entity:brand` → 0 hits.
7. ~~What does a no-match response look like?~~ **ANSWERED 2026-10-16 (live)**: 200 `{"success": true, "results": {"entities": []}}` — distinct from 400 `{"errors": [...]}`.
8. What is the response size for a typical call? (PARTIAL 2026-10-16 live: 20 entities per call by default; verbose `tags/properties/references`; `limit` param max still UNVERIFIED.)
9. Does the starter kit contain a client or schema we should reuse? (Human decision 2026-10-16: not needed for G1; web-search only if blocked. Reuse only if it fits the adapter boundary.)
