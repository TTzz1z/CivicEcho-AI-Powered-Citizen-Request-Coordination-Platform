param(
  [Parameter(Mandatory=$true)][string]$InputFile,
  [switch]$Force,
  [string]$Project = ''
)
$ErrorActionPreference = 'Stop'
if (-not $Force) { throw 'Restore overwrites the target database. Re-run with -Force.' }
$absolute = [IO.Path]::GetFullPath((Join-Path (Get-Location) $InputFile))
if (-not (Test-Path $absolute)) { throw "Backup file does not exist: $absolute" }
$compose = @('compose')
if ($Project) { $compose += @('-p', $Project) }
$container = (docker @compose ps -q postgres).Trim()
if (-not $container) { throw 'PostgreSQL container is not running.' }
docker cp $absolute "${container}:/tmp/tingting-restore.dump"
docker exec $container sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges /tmp/tingting-restore.dump'
if ($LASTEXITCODE -ne 0) { throw 'pg_restore failed.' }
docker exec $container rm -f /tmp/tingting-restore.dump | Out-Null
docker @compose up -d --wait backend
if ($LASTEXITCODE -ne 0) { throw 'Backend failed to start after restore.' }
docker @compose exec -T backend alembic current
docker @compose exec -T -e VERIFY_TICKET_ID backend python -m app.verify_restore
