function Initialize-CivicCompose([string]$Project, [switch]$Production, [string]$EnvFile) {
  $repository = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
  $script:CivicComposeArgs = @('compose', '--project-directory', $repository, '-f',
                               (Join-Path $repository 'docker-compose.yml'))
  if ($Production) {
    $script:CivicComposeArgs += @('-f', (Join-Path $repository 'docker-compose.prod.yml'))
    if (-not $EnvFile) { $EnvFile = Join-Path $repository '.env.prod' }
  }
  if ($EnvFile) { $script:CivicComposeArgs += @('--env-file', (Resolve-Path -LiteralPath $EnvFile).Path) }
  if ($Project) { $script:CivicComposeArgs += @('-p', $Project) }
}

function Invoke-CivicCompose([string[]]$Command) {
  & docker @script:CivicComposeArgs @Command
  if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose operation '$($Command[0])' failed with exit code $LASTEXITCODE."
  }
}

function Assert-CivicQuiescent {
  $writers = @(Invoke-CivicCompose @('ps', '--status', 'running', '--services') |
    Where-Object { $_ -in @('backend', 'worker') })
  if ($writers.Count) {
    throw 'Stop backend and worker before backup or restore.'
  }
}

function Get-CivicAbsolutePath([string]$Path) {
  [IO.Path]::GetFullPath($Path, (Get-Location).ProviderPath)
}

function Restore-CivicDatabase([string]$Dump) {
  $tableCount = @(Invoke-CivicCompose @('exec', '-T', 'postgres', 'sh', '-c',
    'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$1"',
    'sh', "SELECT count(*) FROM information_schema.tables WHERE table_type = 'BASE TABLE' AND table_schema NOT IN ('pg_catalog', 'information_schema')"))
  if (($tableCount -join '').Trim() -ne '0') { throw 'Target PostgreSQL database is not empty.' }
  $nativeDump = "/tmp/civicecho-restore-$([guid]::NewGuid().ToString('N')).dump"
  try {
    Invoke-CivicCompose @('cp', $Dump, "postgres:${nativeDump}")
    Invoke-CivicCompose @('exec', '-T', 'postgres', 'sh', '-c',
                          'pg_restore --exit-on-error --single-transaction --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$1"',
                          'sh', $nativeDump)
  } finally {
    Clear-CivicNativeDump $nativeDump
  }
}

function Clear-CivicNativeDump([string]$NativeDump) {
  try {
    Invoke-CivicCompose @('exec', '-T', 'postgres', 'rm', '-f', $NativeDump)
  } catch {
    Write-Warning "Could not remove the temporary PostgreSQL archive $NativeDump."
  }
}
