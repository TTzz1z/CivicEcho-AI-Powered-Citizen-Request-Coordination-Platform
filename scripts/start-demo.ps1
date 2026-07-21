param([string]$Password = $env:SEED_PASSWORD)
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\check-demo.ps1" -Password $Password -Start -Build
exit $LASTEXITCODE
