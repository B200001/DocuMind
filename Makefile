.PHONY: up down logs dev seed eval

# ─── Docker Compose ───────────────────────────────────────

## Start all services in detached mode
up:
	docker compose up -d

## Stop and remove containers (keeps volumes)
down:
	docker compose down

## Tail logs for all services (Ctrl+C to exit)
logs:
	docker compose logs -f

# ─── Local Dev ────────────────────────────────────────────

## Start backend (FastAPI) + frontend (Next.js) in parallel
dev:
	@echo "Starting backend and frontend..."
	@trap 'kill 0' SIGINT; \
	(cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000) & \
	(cd frontend && npm run dev) & \
	wait

# ─── Data / Evals ─────────────────────────────────────────

## Seed the vector store with sample documents
seed:
	cd backend && .venv/bin/python scripts/seed.py

## Run evaluation suite
eval:
	cd backend && .venv/bin/python scripts/eval.py