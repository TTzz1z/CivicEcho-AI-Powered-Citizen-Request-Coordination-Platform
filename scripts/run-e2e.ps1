param(
  [string]$Password = $env:E2E_PASSWORD,
  [ValidateSet('smoke', 'full')][string]$Suite = 'full',
  [string]$ArtifactDirectory = (Join-Path ([IO.Path]::GetTempPath()) 'Playwright/CivicEcho-E2E')
)
$ErrorActionPreference = 'Stop'
if (-not $Password -or $Password.Length -lt 12) { throw 'Set E2E_PASSWORD or -Password to at least 12 characters.' }
$project = 'tingting-e2e'
$env:E2E_PASSWORD=$Password; $env:SEED_PASSWORD=$Password; $env:SEED_PROFILE='e2e'
$env:POSTGRES_DB='tingting_e2e'; $env:POSTGRES_USER='tingting_e2e'; $env:POSTGRES_PASSWORD='e2e-postgres-isolated-only'
$env:JWT_SECRET='e2e-jwt-secret-isolated-at-least-32-characters'; $env:SERVICE_API_TOKEN='e2e-service-token-isolated-at-least-32-chars'
$env:FRONTEND_PORT='18081'; $env:BACKEND_PORT='18001'
$env:MINIO_API_PORT='29010'; $env:MINIO_CONSOLE_PORT='29011'
$env:E2E_BASE_URL='http://127.0.0.1:18081'; $env:CORS_ORIGINS=$env:E2E_BASE_URL
$env:E2E_API_URL='http://127.0.0.1:18001'
$env:VITE_DEMO_MODE='true'
$env:AI_PROVIDER='rules'; $env:AI_API_KEY=''; $env:EMBEDDING_API_KEY=''
$env:LOGIN_RATE_LIMIT_ATTEMPTS='100'; $env:WORKER_SCAN_INTERVAL_SECONDS='1'
$artifacts = (New-Item -ItemType Directory -Path $ArtifactDirectory -Force).FullName
$env:E2E_OUTPUT_DIR=Join-Path $artifacts 'test-results'
$previousTemp=$env:TEMP; $previousTmp=$env:TMP
$env:TEMP=$artifacts; $env:TMP=$artifacts
function Invoke-E2ECompose { docker compose --env-file .env.example -p $project @args }

Push-Location "$PSScriptRoot\.."
try {
  Invoke-E2ECompose up -d --build --wait
  if ($LASTEXITCODE -ne 0) { throw 'E2E Docker environment failed to start.' }
  Invoke-E2ECompose exec -T -e SEED_PASSWORD -e SEED_PROFILE backend python -m app.seed
  if ($LASTEXITCODE -ne 0) { throw 'E2E seed failed.' }
  if ($Suite -eq 'full') {
    $env:VITE_DEMO_MODE='false'
    Invoke-E2ECompose build frontend
    if ($LASTEXITCODE -ne 0) { throw 'Production-mode E2E frontend build failed.' }
    Invoke-E2ECompose run -d --no-deps --name "$project-prod-entry" -p 127.0.0.1:18082:80 frontend
    if ($LASTEXITCODE -ne 0) { throw 'Production-mode E2E frontend failed to start.' }
    $env:E2E_PRODUCTION_URL='http://127.0.0.1:18082'
  }
  Push-Location "$PSScriptRoot\..\frontend"
  try {
    if ($Suite -eq 'smoke') {
      & ./node_modules/.bin/playwright.cmd test e2e/smoke.spec.ts e2e/boundary-regression.spec.ts --project=chromium
    } else {
      & ./node_modules/.bin/playwright.cmd test --project=chromium
    }
    if ($LASTEXITCODE -ne 0) { throw 'Playwright tests failed.' }
  } finally { Pop-Location }
} finally {
  try { Invoke-E2ECompose down -v --remove-orphans } finally {
    Pop-Location
    $env:TEMP=$previousTemp; $env:TMP=$previousTmp
  }
}
