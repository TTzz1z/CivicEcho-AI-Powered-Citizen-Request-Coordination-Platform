<#
.SYNOPSIS
    Verify and restore a PostgreSQL and S3 archive to a stopped, empty deployment.
#>
param(
  [Parameter(Mandatory)][string]$BackupDir,
  [Parameter(Mandatory)][string]$Project,
  [switch]$Production,
  [string]$EnvFile,
  [switch]$Force
)
$ErrorActionPreference = 'Stop'
if (-not $Force) { throw 'Restore requires -Force with an explicit empty target project.' }
. "$PSScriptRoot\backup-common.ps1"
Initialize-CivicCompose -Project $Project -Production:$Production -EnvFile $EnvFile
Assert-CivicQuiescent

$absolute = Get-CivicAbsolutePath $BackupDir
$manifest = Join-Path $absolute 'checksums.sha256'
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
  throw 'The backup is missing checksums.sha256.'
}
$checksums = @{}
foreach ($line in (Get-Content -LiteralPath $manifest)) {
  if ($line -notmatch '^([a-fA-F0-9]{64})  (postgres[.]dump|object-storage[.]zip)$') {
    throw 'Unexpected checksum record. Legacy raw-volume packages require an isolated legacy restore.'
  }
  if ($checksums.ContainsKey($Matches[2])) { throw 'Duplicate checksum record.' }
  $checksums[$Matches[2]] = $Matches[1]
}
foreach ($name in @('postgres.dump', 'object-storage.zip')) {
  $path = Join-Path $absolute $name
  if (-not $checksums.ContainsKey($name) -or
      (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $checksums[$name]) {
    throw "Backup checksum failed for $name."
  }
}

$snapshotRunner = @('run', '--rm', '--no-deps', '-T', '--user', '0',
                    '--volume', "${absolute}:/snapshot:ro",
                    'backend', 'python', '-m', 'app.object_snapshot')
Invoke-CivicCompose ($snapshotRunner + @('check', '/snapshot/object-storage.zip'))
Restore-CivicDatabase -Dump (Join-Path $absolute 'postgres.dump')
Invoke-CivicCompose ($snapshotRunner + @('restore', '/snapshot/object-storage.zip'))
Invoke-CivicCompose @('run', '--rm', '--no-deps', '-T', '-e', 'VERIFY_TICKET_ID',
                      'backend', 'python', '-m', 'app.verify_restore')
Write-Output "恢复完成: $absolute"
