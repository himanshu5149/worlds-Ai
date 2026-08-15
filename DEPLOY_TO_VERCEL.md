# 🚀 Deploy Prism AI from the GitHub repo

This guide assumes you pasted the **whole repo** into GitHub (see README § "Paste into GitHub").
Everything ships in one repo; the two halves deploy to two hosts:

| Part | Host | Repo path / setting |
| --- | --- | --- |
| **Frontend** (Next.js) | **Vercel** | Root Directory = `frontend` |
| **Backend** (FastAPI) | Railway / Render / Fly.io / VPS | Root Directory = `backend` (Docker) |

> Vercel **cannot** run the FastAPI backend — it is a long-running process (async SQLAlchemy
> engine, 30 s health-check loop, SSE streaming), not a serverless function. Until the backend
> is deployed, the frontend runs in a clearly-labeled **demo mode** so you can explore the UI.

---

## Step 1 — Deploy the frontend to Vercel (~2 minutes)

1. In Vercel: **Add New → Project → Import** your GitHub repo. Next.js is auto-detected.
2. **Project → Settings → General → Root Directory → `frontend`**.
3. Deploy. Open the app — `/` landing, `/chat` (demo mode), `/admin` dashboard.

### Environment variables (Project → Settings → Environment Variables)
| Variable | Value | Notes |
| --- | --- | --- |
| `PRISM_API_PROXY_URL` | `https://your-backend-host.example` | **Set after Step 2.** The browser calls `/api/*` same-origin; Vercel's edge proxies to your FastAPI backend — no CORS needed. |
| `NEXT_PUBLIC_API_URL` | *(leave unset on Vercel)* | Only for local dev against `localhost:8000` |

> The rewrite is baked at **build time** — after adding/changing `PRISM_API_PROXY_URL`, redeploy
> (any commit, or *Deployments → Redeploy*). Pushing to GitHub triggers CI (backend tests +
> frontend build) automatically before you redeploy.

---

## Step 2 — Deploy the backend (~5 minutes, Railway example)

1. Railway: **New Project → Deploy from GitHub repo**. It auto-detects the Dockerfile —
   set **Root Directory = `backend`** in the service settings.
2. Add service variables (Railway → Variables). Minimal set:

   | Variable | Example |
   | --- | --- |
   | `PRISM_JWT_SECRET` | `python -c "import secrets;print(secrets.token_hex(32))"` — 64 hex chars |
   | `PRISM_ENV` | `prod` |
   | `PRISM_DATABASE_URL` | Railway **Postgres** plugin → copy its `DATABASE_URL`, switch scheme to `postgresql+asyncpg://…` |
   | `PRISM_REDIS_URL` | Redis plugin URL (queue / rate limits) |
   | `PRISM_ALLOW_MOCK_PROVIDERS` | `false` |
   | (optional) `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, … | official keys only — the system works and degrades gracefully without them |
3. Enable the **pgvector** extension on your Postgres (Railway → Data tab, or
   `CREATE EXTENSION IF NOT EXISTS vector;`).
4. Run migrations once (deploy → open shell):
   ```bash
   cd backend && alembic upgrade head
   ```
5. Copy the public URL (e.g. `https://prism-api.up.railway.app`), set it as
   `PRISM_API_PROXY_URL` on Vercel, **redeploy**.

**Verify:** open `https://<your-app>.vercel.app/chat` → the "demo mode" chip disappears,
register/login works, and questions return real Prism answers (or an honest
"no model available" message when no provider keys are configured).

---

## What works with zero API keys
- Full chat flow with **honest graceful degradation** (`no_model_available` — answers are never fabricated)
- Health dashboard: keyless cloud models flip to `AUTH_REQUIRED`, unreachable local models to `DOWN`, alerts fire
- Anonymized candidates, EMA feedback, uploads validation, one-call data deletion

Add one official key (e.g. `OPENAI_API_KEY`) for real fan-out; add more providers or an Ollama
instance to see multi-model judging, fusion and cache hits in action.

## Security checklist (5 musts)
- [ ] `PRISM_JWT_SECRET` + `PRISM_CREDENTIAL_ENCRYPTION_KEY` set from a secrets manager
- [ ] `PRISM_ALLOW_MOCK_PROVIDERS=false` (never enable outside local demos)
- [ ] Backend database private (not publicly routable)
- [ ] HTTPS on both hosts (Vercel + Railway do this automatically)
- [ ] Review `docs/DEPLOYMENT.md` hardening list before real user traffic

Full docs in the repo: `docs/API.md`, `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`,
`docs/RISK_REGISTER.md`, `docs/DESIGN_SYSTEM.md`.
