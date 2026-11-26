#!/bin/sh
set -eu
: "${E2E_PASSWORD:?Set E2E_PASSWORD to at least 12 characters}"
[ "${#E2E_PASSWORD}" -ge 12 ] || { echo "E2E_PASSWORD must be at least 12 characters" >&2; exit 2; }
export SEED_PASSWORD="$E2E_PASSWORD" SEED_PROFILE=e2e
export POSTGRES_DB=tingting_e2e POSTGRES_USER=tingting_e2e POSTGRES_PASSWORD=e2e-postgres-isolated-only
export JWT_SECRET=e2e-jwt-secret-isolated-at-least-32-characters SERVICE_API_TOKEN=e2e-service-token-isolated-at-least-32-chars
export FRONTEND_PORT=18081 BACKEND_PORT=18001
export MINIO_API_PORT=29010 MINIO_CONSOLE_PORT=29011
export VITE_DEMO_MODE=true
export AI_PROVIDER=rules AI_API_KEY= EMBEDDING_API_KEY=
# Prefer 127.0.0.1 to avoid CI runners resolving localhost to ::1 while Compose binds IPv4.
export E2E_BASE_URL=http://127.0.0.1:18081
export E2E_API_URL=http://127.0.0.1:18001
export CORS_ORIGINS=http://127.0.0.1:18081
export LOGIN_RATE_LIMIT_ATTEMPTS=100 WORKER_SCAN_INTERVAL_SECONDS=1
PROJECT=tingting-e2e
compose() { docker compose --env-file .env.example -p "$PROJECT" "$@"; }
cleanup() { compose down -v --remove-orphans; }
trap cleanup EXIT INT TERM
compose up -d --build --wait
compose exec -T -e SEED_PASSWORD -e SEED_PROFILE backend python -m app.seed
SUITE="${1:-full}"
if [ "$SUITE" = "smoke" ]; then
  (cd frontend && ./node_modules/.bin/playwright test e2e/smoke.spec.ts e2e/boundary-regression.spec.ts --project=chromium)
else
  VITE_DEMO_MODE=false compose build frontend
  compose run -d --no-deps --name "$PROJECT-prod-entry" -p 127.0.0.1:18082:80 frontend
  export E2E_PRODUCTION_URL=http://127.0.0.1:18082
  (cd frontend && ./node_modules/.bin/playwright test)
fi
