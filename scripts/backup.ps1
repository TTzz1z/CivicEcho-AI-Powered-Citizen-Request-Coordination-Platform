<#
.SYNOPSIS
    Export a consistent PostgreSQL and S3 snapshot while application writers are stopped.
#>
param(
  [string]$OutputDir = "backups\tingting-$((Get-Date).ToString('yyyyMMdd-HHmmss'))",
  [string]$Project = '',
  [switch]$Production,
  [string]$EnvFile
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\backup-common.ps1"
Initialize-CivicCompose -Project $Project -Production:$Production -EnvFile $EnvFile
Assert-CivicQuiescent

$absolute = Get-CivicAbsolutePath $OutputDir
if (Test-Path -LiteralPath $absolute) { throw 'The backup destination already exists.' }
New-Item -ItemType Directory -Path $absolute | Out-Null
if (-not $IsWindows) {
  chmod 700 $absolute
  if ($LASTEXITCODE -ne 0) { throw 'Cannot restrict permissions on backup output directory.' }
}

$runId = [guid]::NewGuid().ToString('N')
$nativeDump = "/tmp/civicecho-backup-$runId.dump"
try {
  Invoke-CivicCompose @('exec', '-T', 'postgres', 'sh', '-c',
                        'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$1"', 'sh', $nativeDump)
  Invoke-CivicCompose @('cp', "postgres:${nativeDump}", (Join-Path $absolute 'postgres.dump'))
  Invoke-CivicCompose @('run', '--rm', '--no-deps', '-T', '--user', '0',
                        '--volume', "${absolute}:/snapshot",
                        'backend', 'python', '-m', 'app.object_snapshot', 'backup', '/snapshot/object-storage.zip')
  Assert-CivicQuiescent
} finally {
  Clear-CivicNativeDump $nativeDump
}

$checksums = foreach ($name in @('postgres.dump', 'object-storage.zip')) {
  "{0}  {1}" -f (Get-FileHash -LiteralPath (Join-Path $absolute $name) -Algorithm SHA256).Hash, $name
}
$checksums | Set-Content -LiteralPath (Join-Path $absolute 'checksums.sha256') -Encoding utf8
Write-Output "备份完成: $absolute"
