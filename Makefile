.PHONY: help dev api web test lint migrate smoke

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

dev: ## Run the full local stack via docker compose
	docker compose -f deploy/docker-compose.yml up --build

api: ## Run the FastAPI backend locally (dev, SQLite)
	cd backend && PRISM_ENV=dev PRISM_DATABASE_URL="sqlite+aiosqlite:///./dev.db" \
	  PRISM_JWT_SECRET=dev-secret-0123456789abcdef0123456789abcdef \
	  uvicorn app.main:app --reload --port 8000

web: ## Run the Next.js frontend locally
	cd frontend && npm run dev

test: ## Run the backend test suite
	cd backend && python -m pytest tests/ -q

lint: ## Lint backend + typecheck frontend build
	cd backend && ruff check app tests
	cd frontend && npm run build

migrate: ## Create/apply Alembic migrations (production)
	cd backend && alembic upgrade head

smoke: ## Quick API smoke test (server must be running)
	curl -s localhost:8000/healthz && echo
