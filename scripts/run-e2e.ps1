param([string]$Password = $env:E2E_PASSWORD)
$ErrorActionPreference = 'Stop'
if (-not $Password -or $Password.Length -lt 12) { throw 'Set E2E_PASSWORD or -Password to at least 12 characters.' }
$project = 'tingting-e2e'
$env:E2E_PASSWORD=$Password; $env:SEED_PASSWORD=$Password; $env:SEED_PROFILE='e2e'
$env:POSTGRES_DB='tingting_e2e'; $env:POSTGRES_USER='tingting_e2e'; $env:POSTGRES_PASSWORD='e2e-postgres-isolated-only'
$env:JWT_SECRET='e2e-jwt-secret-isolated-at-least-32-characters'; $env:SERVICE_API_TOKEN='e2e-service-token-isolated-at-least-32-chars'
$env:FRONTEND_PORT='18081'; $env:BACKEND_PORT='18001'; $env:RASA_PORT='15005'; $env:ACTION_SERVER_PORT='15055'; $env:DUCKLING_PORT=if($env:E2E_DUCKLING_PORT){$env:E2E_DUCKLING_PORT}else{'28000'}
$env:MINIO_API_PORT='29010'; $env:MINIO_CONSOLE_PORT='29011'
$env:E2E_BASE_URL='http://localhost:18081'; $env:CORS_ORIGINS='http://localhost:18081'; $env:RASA_CORS_ORIGIN='http://localhost:18081'
try {
  docker compose -p $project up -d --build --wait
  if ($LASTEXITCODE -ne 0) { throw 'E2E Docker environment failed to start.' }
  docker compose -p $project exec -T -e SEED_PASSWORD -e SEED_PROFILE backend python -m app.seed
  if ($LASTEXITCODE -ne 0) { throw 'E2E seed failed.' }
  Push-Location "$PSScriptRoot\..\frontend"
  try {
    npm exec playwright test
    if ($LASTEXITCODE -ne 0) { throw 'Playwright tests failed.' }
  } finally { Pop-Location }
} finally {
  docker compose -p $project down -v --remove-orphans
}
