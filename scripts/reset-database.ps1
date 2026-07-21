param([switch]$Force, [string]$Password = $env:SEED_PASSWORD)
$ErrorActionPreference = 'Stop'
if (-not $Force) { throw 'This deletes the current Docker volume. Re-run with -Force.' }
if (-not $Password -or $Password.Length -lt 12) { throw 'Set SEED_PASSWORD or -Password to at least 12 characters.' }
docker compose down -v --remove-orphans
if ($LASTEXITCODE -ne 0) { throw 'Database cleanup failed.' }
& "$PSScriptRoot\start-demo.ps1" -Password $Password
