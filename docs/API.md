# API reference

Base: `/api/v1` · Interactive docs: `/docs` (OpenAPI) · Metrics: `/metrics` (Prometheus) · Liveness: `/healthz`

**Auth**: `Authorization: Bearer <JWT>` (HS256 default; configure a strong `PRISM_JWT_SECRET`). Roles: `user`, `admin`.

**Error model** (RFC-7807-ish):
```json
{ "error": "no_model_available", "message": "...", "detail": {}, "request_id": "0a1b…" }
```
Stable error codes: `unauthorized · forbidden · not_found · validation_failed · rate_limited · no_model_available · request_queued · email_taken · internal_error`. Every response carries `X-Request-ID`.

## Auth
| Method & path | Body | Returns |
| --- | --- | --- |
| `POST /auth/register` | `{email, password (8-128), display_name?}` | `201 {access_token, role, expires_in_minutes}` |
| `POST /auth/login` | `{email, password}` | `200 {access_token, role, …}` |
| `POST /auth/logout` | — | `204` (client drops token) |
| `GET /auth/me` | — | `200 {id, email, role, display_name, preferences}` |

Auth endpoints are rate-limited (sliding window per IP, Redis-backed in prod). Passwords are hashed (PBKDF2-SHA256, constant-time compare).

## Chat
| Method & path | Body | Returns |
| --- | --- | --- |
| `POST /chat` | `{message (≤16k), conversation_id?, attachments?: [uuid] (≤5), preferences?, stream?: bool}` | `200` `{request_id, answer, status, from_cache, fused, latency_ms, message?, error?, queue_position?}` |
| `POST /chat` with `stream: true` | same | `text/event-stream`: `meta` → `token*` → `done` (streaming starts after judging; documented trade-off) |
| `GET /chat/conversations` | — | `200 [conversation]` |
| `GET /chat/conversations/{id}` | — | `200 {conversation, messages[], requests[]}` (owner-only; 404 otherwise) |
| `DELETE /chat/conversations/{id}` | — | `204` |
| `POST /chat/{request_id}/feedback` | `{rating: 1\|-1, comment?}` | `200 {accepted, weight_updates[]}` — updates routing weights via EMA |
| `GET /chat/{request_id}/candidates` | query `reveal` (default false) | `200 {revealed, candidates: [{label: "Candidate A", text, score_pct, is_winner, fused, model_id?, provider?}]}` — model fields populated **only** when an admin sets `reveal=true` (audited) |
| `GET /chat/requests/{request_id}` | — | `200 {request_id, status, answer?, error?}` — poll for queued requests |

`status` values: `completed · from_cache · queued · failed`. A `failed` chat response still returns HTTP 200 with `error: "no_model_available"` and `answer: null` — the message is honest, never fabricated. `queued` means the request was accepted for background processing (Celery) when no model was available.

## Files
| Method & path | Notes |
| --- | --- |
| `POST /files/upload` | multipart `file`; ≤ `PRISM_MAX_UPLOAD_MB` (10 MB); allow-list: txt/md/csv/json/pdf/docx/png/jpg + magic-byte sniffing; returns `201 {file_id, original_name, mime_type, size_bytes, extracted_chars}` |
| `DELETE /files/{file_id}` | `204` |

Extracted text is wrapped in `<user_document>` tags server-side before reaching any model (prompt-injection containment).

## Admin (role `admin`)
| Method & path | Notes |
| --- | --- |
| `GET /admin/models` | registry incl. capabilities, verification flags, credential requirements |
| `PATCH /admin/models/{id}` | `{status?, routing_weight?}` — manual override |
| `POST /admin/models/{id}/health-check` | immediate probe, result + event recorded |
| `POST /admin/credentials` | `{provider, api_key, note}` — stored Fernet-encrypted; replaces cached adapter key |
| `GET /admin/metrics` | 24h aggregates: requests, success rate, p95 latency, cache hit rate, fused count, per-model cards |
| `GET /admin/alerts` | active DOWN/PAID/AUTH/DEGRADED alerts |
| `GET /admin/health-events` | probe history (`model_id`, `limit`) |

## Privacy
| Method & path | Notes |
| --- | --- |
| `DELETE /me/data` | full erasure (see DATABASE.md deletion semantics); returns per-table counts + `account_deleted` |

## Examples

```bash
TOKEN=$(curl -s -X POST $BASE/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"correct-horse-battery"}' | jq -r .access_token)

curl -s -X POST $BASE/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"What is the capital of France?"}' | jq .

curl -s "$BASE/api/v1/chat/<request_id>/candidates" \
  -H "Authorization: Bearer $TOKEN" | jq '.candidates[] | {label, score_pct, is_winner}'
```
