# Deployment guide

## 1. Local (Docker Compose)

```bash
cp .env.example .env                 # fill in any API keys you have
docker compose -f deploy/docker-compose.yml up --build
```

Starts: `postgres` (pgvector/pgvector:pg16), `redis:7`, `api` (FastAPI, port 8000), `worker` (Celery), `web` (Next.js, port 3000), `ollama`. Pull a local model for the fallback tier:

```bash
docker compose -f deploy/docker-compose.yml exec ollama ollama pull llama3.2
```

Run Alembic before first prod deploy (the API creates tables automatically only in dev): `cd backend && alembic upgrade head`.

## 2. Production topology

```
                         ┌──────────────────────────────┐
  Users ──TLS──► Caddy/LB├─ /            → Next.js (static + SSR)
                         ├─ /api/* /healthz → FastAPI × N (stateless)
                         └─ /metrics     → scrape by Prometheus
                          │
FastAPI ──► Managed Postgres 16 + pgvector (RDS/Cloud SQL/Neon)
        ──► Managed Redis (ElastiCache/Upstash)   ← Celery broker + rate limits
        ──► Object storage (S3-compatible)        ← uploads
        ──► Ollama (self-hosted, optional GPU)    ← local fallback tier
```

`deploy/docker-compose.prod.yml` is the reference (2× API, 2× Celery workers, Caddy with automatic HTTPS — set your domain in `Caddyfile`). For Kubernetes, treat the same pieces as Deployments/StatefulSets; the API is fully stateless (all state lives in Postgres/Redis/object storage).

### Hardening checklist
- [ ] `PRISM_JWT_SECRET` = 64 hex chars, unique per environment; `PRISM_CREDENTIAL_ENCRYPTION_KEY` = Fernet key from a secrets manager/KMS (never in git).
- [ ] TLS 1.2+ everywhere; HSTS on the edge; `PRISM_ENV=prod`.
- [ ] `PRISM_ALLOW_MOCK_PROVIDERS=false` (must never be true outside demos).
- [ ] CORS restricted to your real origins.
- [ ] Postgres: private subnet, encrypted at rest, automated snapshots/PITR; rotate credentials.
- [ ] Redis: password + TLS; separate logical DBs for queue vs cache.
- [ ] Object storage: private bucket, lifecycle rule for expired uploads, server-side encryption.
- [ ] Logs to a collector with retention limits; **bodies are never logged**; PII redaction on.
- [ ] Prometheus alert rules: `prism_model_status{value<0}`, `prism_chat_requests_total{outcome="failed"}` rate, quota-exhaustion counters (`prism_provider_errors_total{error_type="QUOTA_EXHAUSTED"}`).
- [ ] Run retention jobs: purge `deleted_at` users, expired cache entries, old health events.
- [ ] Restrict the admin endpoints with the `admin` role; review `audit_events` for `admin.reveal_candidates`.

## 3. Environment variables

Complete annotated template: [`.env.example`](../.env.example). Highlights:

| Variable | Default | Meaning |
| --- | --- | --- |
| `PRISM_MAX_FANOUT_MODELS` | 4 | concurrent models per request |
| `PRISM_SOFT_TIMEOUT_S` / `PRISM_HARD_TIMEOUT_S` | 8 / 20 | fan-out deadlines |
| `PRISM_HEALTH_CHECK_INTERVAL_S` | 30 | probe cadence |
| `PRISM_CACHE_SIMILARITY_THRESHOLD` | 0.92 | cache guardrail |
| `PRISM_CACHE_TTL_HOURS` | 24 | entry lifetime |
| `PRISM_JUDGE_QUALITY_GATE` | 0.55 | minimum acceptable score |
| `PASTEL_THEME_PRIMARY` etc. | pastel palette | design-system tokens |
| `OPENAI_API_KEY` … `XAI_API_KEY` | — | official credentials (never assume free tiers) |
| `PRISM_EMBEDDING_BACKEND` | `local-hash` | `local-hash` \| `openai` \| `ollama` |
| `PRISM_QUEUE_ENABLED` | false | enable Celery queue stage |
| `PRISM_ALLOW_MOCK_PROVIDERS` | **false** | demo stubs only |

## 4. Operations playbook (excerpts)

- **Provider 429 storm** → health manager moves models to `COOLING` (respects `retry-after`), orchestrator routes around them; watch `prism_provider_errors_total`.
- **Quota exhausted** → model flips to `PAID_REQUIRED` (passive signal, instant); admin gets an alert; add/replace the credential via `POST /admin/credentials` — the cached adapter is refreshed immediately.
- **Auth key rotated** → status `AUTH_REQUIRED` until the new key is supplied; probes continue every ~30 s to detect recovery.
- **Everything down** → fallback ladder ends in queue (202) or honest failure; no fabricated answers; users see a transparent message.
- **Verify an unverified connector** → it only ever runs with `ALLOW_MOCK_PROVIDERS=true` and is excluded from production eligibility regardless; to graduate it, implement + test the real endpoint, then flip `requires_verification=False`.
