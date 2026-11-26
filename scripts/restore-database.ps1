param(
  [Parameter(Mandatory=$true)][string]$InputFile,
  [switch]$Force,
  [Parameter(Mandatory)][string]$Project,
  [switch]$Production,
  [string]$EnvFile
)
$ErrorActionPreference = 'Stop'
if (-not $Force) { throw 'Database restore requires -Force with an explicit target project.' }
. "$PSScriptRoot\backup-common.ps1"
Initialize-CivicCompose -Project $Project -Production:$Production -EnvFile $EnvFile
Assert-CivicQuiescent
$absolute = Get-CivicAbsolutePath $InputFile
if (-not (Test-Path -LiteralPath $absolute -PathType Leaf)) { throw "Backup file does not exist: $absolute" }
Restore-CivicDatabase -Dump $absolute
Invoke-CivicCompose @('run', '--rm', '--no-deps', '-T', '-e', 'VERIFY_TICKET_ID',
                      'backend', 'python', '-m', 'app.verify_restore', '--database-only')
