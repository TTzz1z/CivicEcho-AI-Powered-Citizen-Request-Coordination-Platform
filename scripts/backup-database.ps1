param(
  [string]$Output = "backups\tingting-$((Get-Date).ToString('yyyyMMdd-HHmmss')).dump",
  [string]$Project = ''
)
$ErrorActionPreference = 'Stop'
$compose = @('compose')
if ($Project) { $compose += @('-p', $Project) }
$container = (docker @compose ps -q postgres).Trim()
if (-not $container) { throw 'PostgreSQL container is not running.' }
docker exec $container sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/tingting-backup.dump'
if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed.' }
$absolute = [IO.Path]::GetFullPath((Join-Path (Get-Location) $Output))
New-Item -ItemType Directory -Force (Split-Path $absolute) | Out-Null
docker cp "${container}:/tmp/tingting-backup.dump" $absolute
docker exec $container rm -f /tmp/tingting-backup.dump | Out-Null
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $absolute)) { throw 'Backup copy failed.' }
Write-Output $absolute
