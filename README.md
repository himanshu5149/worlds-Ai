# Prism AI

**One question. Many minds. One answer.**

Prism AI is a web-first platform where a user asks a question once. The system routes the question to multiple eligible AI models **in parallel**, evaluates every answer with a two-stage hybrid judge, selects or safely fuses the best answer, and returns a single high-quality response — **without ever revealing which provider or model produced it**.

This repository contains a production-ready reference implementation: FastAPI backend, Next.js frontend with a strict **Pastel / Soft UI** design system, PostgreSQL(+pgvector) schema, semantic cache with guardrails, health manager, fallback chain, feedback loop, admin dashboard, full test suite, and deployment assets.

> Also known internally as the "AI Arena Hub" reference design — same product, this is the canonical build.

---

## 1. Executive summary

| Concern | How Prism handles it |
| --- | --- |
| **Multi-model answers** | Fan-out orchestrator runs up to 4 eligible models concurrently with per-model hard timeouts (soft 8 s / hard 20 s default) and a global soft deadline. |
| **Hidden model identity** | The assistant is always "Prism". Self-identification in model output is stripped by the safety gate; provider error strings are rejected outright; "Compare Answers" shows anonymized Candidate A/B/C; admin reveal requires the admin role **and** writes an audit event. |
| **Legal / ToS compliance** | Official APIs only (httpx against each provider's documented REST surface — OpenAI, Anthropic, Google Gemini, Mistral, Cohere v2, DeepSeek, xAI, Ollama). No scraping, no browser automation, no account rotation, no free-tier assumptions. Unverified connectors are config-driven stubs marked `requires_verification` and **refuse to run** unless explicitly enabled for local demos. |
| **Graceful degradation** | Fallback ladder: eligible cloud models → user/admin-provided official keys → local Ollama models → high-confidence semantic cache (stricter thresholds) → queue (202) → honest failure message. **Answers are never fabricated.** |
| **Reliability** | Health manager probes every 30 s (or passively on live traffic): 2 consecutive failures → `DEGRADED`, 5 → `DOWN`, rate-limit → `COOLING` with exponential backoff + jitter, auth/quota → `AUTH_REQUIRED` / `PAID_REQUIRED`. Typed error categories: `RATE_LIMITED`, `QUOTA_EXHAUSTED`, `AUTH_EXPIRED`, `PAID_REQUIRED`, `REGION_BLOCKED`, `TIMEOUT`, `CONTENT_POLICY`. |
| **Quality** | Hybrid judge: hard safety gate, then heuristic scoring — relevance 35 %, factuality 30 %, completeness 15 %, readability 10 %, latency 10 % — with an optional local judge model for tie-breaking. Top-2 fusion only when both pass the quality bar, don't contradict, and fusion re-scores ≥ winner. |
| **Cost/latency** | Semantic cache (pgvector) with strict guardrails: cosine ≥ 0.92, intent match, language match, entity match, time-sensitivity freshness, confidence ≥ 0.85, 24 h TTL. Cache never overrides safety. |
| **Feedback** | Thumbs up/down update routing weights via EMA (α = 0.1, early-sample dampening, clamped [0.1, 2.5]) — gradual, no overreaction. |
| **Privacy** | TLS everywhere, encrypted credentials at rest (Fernet/KMS-ready), RBAC, PII redaction in logs, uploads treated as untrusted `<user_document>` input, one-call data deletion (`DELETE /api/v1/me/data`) covering messages, conversations, requests, invocations, scores, feedback, uploads (+files), cache entries and audit trail. |
| **Observability** | Prometheus metrics (`/metrics`), structured JSON logs with request IDs (bodies never logged), OpenTelemetry hooks, health dashboard with alerts. |

**Verification performed in this build** (see §7): 88 backend tests passing, lint clean, live smoke tests against the running server (auth → graceful degradation → fan-out → anonymized candidates → feedback → cache hit → data deletion), Alembic migration executed, frontend production build passing.

---

## 2. Design system — "Pastel / Soft UI"

Prism's visual identity follows a **Pastel / Soft UI** language. These rules are encoded as Tailwind design tokens in `frontend/tailwind.config.ts` and are non-negotiable across every surface.

### Color palette (mesh gradient)
| Token | Hex | Usage |
| --- | --- | --- |
| `lavender` | `#E9D5FF` | primary brand tint, Prism avatar glow, active states |
| `mint` | `#A7F3D0` | success, thumbs-up, healthy status dots |
| `peach` | `#FED7AA` | user bubbles, warnings, degraded status |
| `babyblue` | `#BFDBFE` | info, cache chips, latency cards |
| `cream` | `#FAFAF9` | light background (never stark white) |
| `night` | `#0F172A` | dark mode background (deep slate/indigo, never pitch black) |

A slow-moving 4-blob mesh gradient (24–46 s ease-in-out drift, `filter: blur(90px)`) floats behind every page (`components/PastelBackground.tsx`).

### Geometry
- **Heavily rounded**: cards `rounded-3xl` / `rounded-[2rem]`, modals `rounded-4xl` (2 rem).
- **Pill-shaped**: every button and chip is `rounded-full`.
- The send button is a **circular gradient button** (`#C084FC → #FB923C → #60A5FA`) with a soft glow and a spring press animation.

### Effects
- **Glassmorphism**: `bg-white/60 backdrop-blur-md border border-white/60` for assistant bubbles and inputs; `bg-white/75 backdrop-blur-xl` for modals/panels. Dark mode: `bg-slate-800/50`, `border-white/10`.
- **Soft diffused shadows**: `shadow-xl shadow-purple-200/50`, `shadow-glow: 0 0 24px rgba(196,181,253,.55)` — never hard black shadows.
- **Animations**: Framer Motion with spring physics (`stiffness 300–400, damping 24–28`); hover actions fade/slide in; typing indicator is three pulsing lavender dots.

### Layout & typography
- Airy, generous padding; centered chat column (max-w-3xl) floating over the mesh background.
- Bento-box dashboard grid with pastel-tinted metric cards.
- **Headings**: Plus Jakarta Sans (fallback Nunito/Quicksand). **Body**: Inter. `letter-spacing: -0.02em` on display type.

### Chat anatomy (spec-compliant)
- **User message**: soft peach→lavender gradient bubble, aligned right, `rounded-3xl rounded-br-lg`.
- **Assistant message**: frosted glass bubble aligned left with a softly glowing "Prism" avatar; says only "Prism" — never a model name.
- **Hover actions**: pill buttons *Copy · Regenerate · Compare Answers* with spring entrance.
- **Input box**: floating pill-shaped glass container; pastel mic/paperclip icons; circular gradient send; dashed pastel drop-zone (10 MB, MIME + magic-byte validation); pulsing pastel waveform while recording.

---

## 3. Repository layout (single repo — paste the whole thing into GitHub)

```
prism-ai/                       <- push this repo to GitHub (one repo, all in one)
├── .github/workflows/ci.yml    <- GitHub Actions: backend tests + frontend build on every push
├── backend/                    <- FastAPI + SQLAlchemy 2 + pgvector + Celery (deploy via Railway/Render/Fly)
│   ├── app/
│   │   ├── core/               # config (pydantic-settings), security, logging, errors
│   │   ├── db/                 # models (16 tables), sessions, bootstrap
│   │   ├── providers/          # adapter ABC + 8 official connectors + gated stub
│   │   ├── health/             # 30s health manager (state machine + backoff)
│   │   ├── orchestrator/       # fan-out, fallback chain, normalize, SSE streaming
│   │   ├── judge/              # safety gate, heuristic scoring, fusion
│   │   ├── cache/              # pgvector semantic cache + guardrails
│   │   ├── feedback/           # EMA weight updater
│   │   ├── embeddings/         # local-hash / OpenAI / Ollama embedders
│   │   ├── queue/              # Celery task for queued requests
│   │   ├── api/v1/             # auth, chat, files, admin, privacy
│   │   └── observability/      # Prometheus + OTel hooks
│   ├── alembic/                # async migrations (0001 verified)
│   ├── tests/                  # 88 tests
│   └── Dockerfile              # for Railway/Render/Fly (root dir = backend)
├── frontend/                   <- Next.js 14 App Router + Tailwind + Framer Motion + Lucide
│   ├── app/                    # landing, chat, admin
│   ├── components/             # pastel UI kit (bubbles, input, mesh, compare modal...)
│   ├── lib/                    # typed API client (+ SSE)
│   ├── vercel.json             # Vercel config (root dir = frontend)
│   └── Dockerfile              # for container deployments
├── deploy/                     # docker-compose (dev + prod), Caddyfile
├── docs/                       # architecture, database, API, deployment, risks, design system
└── README.md · DEPLOY_TO_VERCEL.md · .env.example · Makefile · .gitignore
```

## 4. Quick start

### Paste into GitHub (all in one)
```bash
unzip prism-ai-github.zip && cd prism-ai
git init && git add -A && git commit -m "Initial import: Prism AI"
git remote add origin https://github.com/<you>/<your-repo>.git
git push -u origin main
```
(Or on github.com: **New repository -> uploading an existing file ->** drag the contents of the `prism-ai/` folder.)
On push, **GitHub Actions** automatically runs the backend test suite and the frontend production build (`.github/workflows/ci.yml`).
Then deploy: **[DEPLOY_TO_VERCEL.md](DEPLOY_TO_VERCEL.md)** — Vercel with *Root Directory = `frontend`*, backend via Railway/Render with *Root Directory = `backend`*.

### Run locally
```bash
# Full local stack (Postgres+pgvector, Redis, API, worker, web, Ollama)
cp .env.example .env
docker compose -f deploy/docker-compose.yml up --build

# Or backend + frontend natively
cd backend && pip install -e '.[dev]' && make api     # port 8000, /docs for OpenAPI
cd frontend && npm install && npm run dev             # port 3000

# Tests
cd backend && python -m pytest tests/ -q              # 88 passed

# Migrations (production)
cd backend && alembic upgrade head
```

### Deploy to the cloud (Vercel + Railway/Render)
See **[DEPLOY_TO_VERCEL.md](DEPLOY_TO_VERCEL.md)**. One-liner: the Next.js frontend deploys to **Vercel** with *Root Directory = `frontend`* (works immediately in labeled demo mode); the FastAPI backend ships as a Docker container for **Railway/Render/Fly.io** with *Root Directory = `backend`* (Vercel cannot run long-lived Python processes); wire them together with one env var (`PRISM_API_PROXY_URL`) and the edge proxy handles routing/CORS.

Without any API keys the system is fully operational and demonstrates **graceful degradation** (see smoke test in §7): chat returns an honest `no_model_available` with a clear message. Add one or more official keys to activate real fan-out; run Ollama (`ollama pull llama3.2`) to enable the local tier; `PRISM_ALLOW_MOCK_PROVIDERS=true` enables the clearly-marked demo stub for local UI demos.

---

## 5. Documentation index

| Doc | Contents |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Mermaid architecture diagram, request lifecycle, component contracts |
| [docs/DATABASE.md](docs/DATABASE.md) | Full 16-table schema, indexes, vector search, deletion semantics |
| [docs/API.md](docs/API.md) | Endpoint reference, auth, error model, examples |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Local compose, production topology, env vars, hardening checklist |
| [docs/RISK_REGISTER.md](docs/RISK_REGISTER.md) | Risk register + pitfall analysis (with mitigations) |
| [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md) | Pastel/Soft UI rules and component recipes |

## 6. Key design decisions (honest trade-offs)

- **Streaming starts after judging.** First token lands after the soft timeout (~8 s worst case), not instantly — the price of hidden identity + multi-model judging. The UI streams the winning model's tokens via its official streaming endpoint and falls back to the stored answer if streaming fails.
- **Passive vs active health probes.** Providers without a free auth-check endpoint (Anthropic, Mistral, Cohere) use passive health (inferred from live traffic); OpenAI/Gemini/DeepSeek/xAI/Ollama support free `GET /models`-style probes. `tiny_prompt` probes are supported but off by default to avoid burning quota.
- **Cache stores only what it may serve.** Entries are written only when the judge score ≥ the cache confidence threshold (0.85), so storage is never wasted on answers the guardrails would refuse.
- **Deterministic heuristics, explainable scores.** Every judge dimension is a deterministic function — reproducible in tests, visible in the audit trail, and cheap. A local judge model is a pluggable tie-breaker (`local_tie_breaker`), not a black box.
- **LocalHashEmbedder is a dev fallback, not production semantics.** Cosine quality with feature hashing is crude; production should configure `PRISM_EMBEDDING_BACKEND=openai` (official embeddings API) or `ollama`.

## 7. What was tested (this build)

- **Unit/integration (88 tests, all green):** safety gate (error leaks, injection echoes, self-ID stripping, PII redaction), judge scoring invariants, fusion (dedupe/complement/contradiction/quality-bar), cache guardrails (every rule + boundary values), health state machine (2→DEGRADED, 5→DOWN, two-stage recovery, backoff, COOLING, passive signals), fan-out (eligibility, ≤4 models, hard timeouts, typed failures, hidden identity, partial failure), fallback ladder (cloud→local→safe cache→queue→failure; no model re-invocation), EMA math + clamping + service persistence, registry seeding/eligibility/stub gating, and 13 end-to-end API tests (auth, RBAC, chat, anonymized candidates, feedback, uploads validation, conversations, full data deletion).
- **Live smoke tests** against a running server: health manager classified keyless cloud models as `AUTH_REQUIRED` and a dead Ollama as `DOWN` over successive 30 s cycles; chat without models returned `no_model_available` (no fabrication); with the demo stub, chat → judge → answer → **cache hit on repeat** → anonymized candidates → EMA feedback → data deletion all verified over HTTP.
- **Tooling:** `ruff` clean (with FastAPI-idiomatic `B008` ignored), Alembic `upgrade head` executed against a fresh database (15 tables + pgvector/HNSW guards), `next build` type-checks and compiles clean.
