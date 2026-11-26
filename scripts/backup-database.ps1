param(
  [string]$Output = "backups\tingting-$((Get-Date).ToString('yyyyMMdd-HHmmss')).dump",
  [string]$Project = '',
  [switch]$Production,
  [string]$EnvFile
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\backup-common.ps1"
Initialize-CivicCompose -Project $Project -Production:$Production -EnvFile $EnvFile
$absolute = Get-CivicAbsolutePath $Output
if (Test-Path -LiteralPath $absolute) { throw 'The backup destination already exists.' }
New-Item -ItemType Directory -Force -Path (Split-Path $absolute) | Out-Null
$nativeDump = "/tmp/civicecho-backup-$([guid]::NewGuid().ToString('N')).dump"
try {
  Invoke-CivicCompose @('exec', '-T', 'postgres', 'sh', '-c',
                        'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$1"', 'sh', $nativeDump)
  Invoke-CivicCompose @('cp', "postgres:${nativeDump}", $absolute)
} finally {
  Clear-CivicNativeDump $nativeDump
}
Write-Output $absolute
