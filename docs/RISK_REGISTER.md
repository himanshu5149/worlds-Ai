# Risk register & pitfall analysis

Severity: **H** high · **M** medium · **L** low. Likelihood: **H/M/L**. Priority = severity × likelihood.

## Legal & ToS

| # | Risk | S×L | Mitigation (implemented / required) |
| --- | --- | --- | --- |
| R1 | Provider ToS violation (unofficial endpoints, scraping, account rotation) | H×M | Only documented official REST endpoints are called (`verified_docs` recorded per adapter). No browser automation anywhere. No consumer-account rotation: one credential per provider per owner. Unverified connectors are stubs that refuse to run outside explicit demo mode. **Required:** periodic re-review of each provider's ToS; automated contract tests against each adapter when keys are present. |
| R2 | Assuming free programmatic access | H×M | No free tiers assumed. Keyless cloud models are reported `AUTH_REQUIRED` and excluded. `PAID_REQUIRED` / `QUOTA_EXHAUSTED` states are first-class. |
| R3 | Rate-limit/quota bypass | H×L | `parse_rate_limit_headers` feeds `COOLING` + exponential backoff with jitter; retries are bounded and honor `retry-after`; no blind retry loops (health backoff cap 15 min). |
| R4 | Endpoint/API-shape drift (provider changes break a connector) | M×M | Config-driven base URLs + model catalog; every adapter maps errors from body patterns with sane defaults; health manager surfaces breakage within 30 s; `requires_verification` flag + docs audit trail. |
| R5 | Model catalog staleness (deprecated model IDs) | M×M | Catalog is data, not code (admin API editable); `404 model not found` typed as `UNKNOWN` and visible in health events. |

## Identity & trust

| # | Risk | S×L | Mitigation |
| --- | --- | --- | --- |
| R6 | Model self-identifies in the answer text | M×M | System prompt forbids it; safety gate strips self-identification patterns (incl. "As an AI created by X"); UI never renders model names; anonymized candidates by default. |
| R7 | Provider error strings leak internals ("rate limit exceeded…") | M×M | Safety gate rejects terse error-leak answers (<300 chars matching error patterns); longer content discussing HTTP errors is allowed deliberately. |
| R8 | Admin reveal abused | M×L | `reveal=true` requires admin role and writes `audit_events` row with actor id. |
| R9 | Identity leak via voice/style fingerprinting | L×M | Documented residual risk: prose style may hint at a model. Optional mitigation: uniform persona prompt + single TTS voice for voice answers. |

## Safety & correctness

| # | Risk | S×L | Mitigation |
| --- | --- | --- | --- |
| R10 | Prompt injection via uploaded files | H×M | Uploads treated as untrusted: `<user_document>` delimiters, 10 MB cap, MIME + magic-byte validation, extraction failure never blocks chat, 20k char extraction cap. |
| R11 | Stale cache answer served | H×M | Guardrail chain (similarity, intent, language, entities incl. exact dates/numbers, time-sensitivity freshness ≤15 min, confidence ≥0.85, TTL). Cache is never consulted for time-sensitive queries unless ultra-fresh; fallback cache stage uses even stricter thresholds. |
| R12 | Judge misranks answers (heuristics are not ground truth) | M×M | Deterministic, explainable dimensions; safety gate is a hard gate (rejects, never passes); fusion only when re-scored ≥ winner; weak answers trigger fallback tiers before being shown. |
| R13 | Fusion invents facts | H×L | Fusion concatenates existing sentences only, dedupes, never generates; contradiction detector aborts; citations preserved. |
| R14 | Fabricated answer when everything fails | H×L | Terminal fallback is an explicit failure/queue message; `answer: null`; stub/mock answers are labelled `[MOCK…]` and require an explicit env flag. |

## Reliability & cost

| # | Risk | S×L | Mitigation |
| --- | --- | --- | --- |
| R15 | Thundering herd / latency pile-up | M×M | Fan-out capped at 4; per-model hard timeout 20 s; soft-deadline early exit; streaming falls back to stored answer. |
| R16 | Cost blow-up (fan-out multiplies tokens) | M×M | Cheap health probes only where free endpoints exist (no paid probes by default); cache-first path; 24h TTL; cost estimates recorded on invocations; budget alerts via Prometheus (to be configured). |
| R17 | Redis/Celery outage blocks chat | M×L | Queue stage is optional; failure path is synchronous and honest without Redis. |
| R18 | pgvector extension missing / index unavailable | M×L | Alembic creates extension; vector candidate lookup falls back to Python cosine on error (logged). |
| R19 | Health flapping (status oscillation) | L×M | Two-stage recovery (DOWN→DEGRADED→ACTIVE), consecutive-success requirements, backoff with jitter. |

## Privacy & security

| # | Risk | S×L | Mitigation |
| --- | --- | --- | --- |
| R20 | Sensitive data in logs | H×L | Bodies/query strings never logged; PII redaction patterns; request IDs only. |
| R21 | Credential exposure | H×L | Fernet at rest, KMS-ready reference; never in responses/logs; rotation via admin API refreshes adapters immediately. |
| R22 | Cross-tenant data leak (cache/conversations) | H×L | Cache entries user-scoped by default; conversations/messages/requests are owner-checked (404 on mismatch); feedback ownership checked. |
| R23 | Deletion incomplete (right to erasure) | M×M | `DELETE /me/data` cascade incl. cache entries derived from user's requests + on-disk files + audit trail; retention job documented for hard purge. |
| R24 | JWT secret weak / shared | H×L | Config-driven; docs mandate 64-hex random; HS256 with secret-length checks (test suite warns). |
| R25 | Model sends PII in answer | M×M | Answer PII redaction (email/phone/card) before display. |

## Known pitfalls (honest engineering notes)

1. **Streaming first-token latency** — judging happens before streaming, so the first token arrives after the soft deadline in the worst case. Accepted trade-off for hidden identity; see `app/orchestrator/streaming.py`.
2. **Heuristic factuality is not verification** — without a verifier model or retrieval, "factuality" measures confidence signals (hedging, contradiction, refusals). For high-stakes domains, plug a retrieval/verification stage into the judge or surface source citations.
3. **LocalHashEmbedder is not semantic** — dev convenience only; real deployments must configure OpenAI (official embeddings endpoint) or Ollama embeddings, otherwise cache similarity quality degrades.
4. **SQLite ≠ production** — it exists so the full stack runs/tests without infra; pgvector paths are PostgreSQL-only.
5. **Provider-specific error bodies change** — `map_error` patterns are config-driven defaults; expect occasional `UNKNOWN` classifications for new provider errors — that's safe-by-default (falls through the chain) and visible in health events.
6. **Model-name mentions in product content are legitimate** — the anonymizer strips *self*-identification only; an answer comparing GPT-4 and Claude keeps those names (they're content, not identity).
7. **Time-sensitivity is keyword-based** — "price today" is caught; oblique temporal intent may not be. Consider an LLM-based time-sensitivity classifier for production.
