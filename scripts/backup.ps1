<#
.SYNOPSIS
    倾听助手 PostgreSQL + MinIO 联合备份
.DESCRIPTION
    生成统一备份包：postgres.dump + minio/ 对象 + manifest.json + checksums.sha256
.EXAMPLE
    .\scripts\backup.ps1
    .\scripts\backup.ps1 -Project tingting-assistant
#>
param(
  [string]$OutputDir = "backups\tingting-$((Get-Date).ToString('yyyyMMdd-HHmmss'))",
  [string]$Project = ''
)
$ErrorActionPreference = 'Stop'
$compose = @('compose')
if ($Project) { $compose += @('-p', $Project) }

$absolute = [IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputDir))
New-Item -ItemType Directory -Force $absolute | Out-Null
Write-Output "备份目标: $absolute"

# --- 1. PostgreSQL dump ---
$pgContainer = (docker @compose ps -q postgres).Trim()
if (-not $pgContainer) { throw 'PostgreSQL container is not running.' }
Write-Output "[1/4] 导出 PostgreSQL..."
docker exec $pgContainer sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/tingting-backup.dump'
if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed.' }
docker cp "${pgContainer}:/tmp/tingting-backup.dump" "$absolute\postgres.dump"
docker exec $pgContainer rm -f /tmp/tingting-backup.dump | Out-Null
if (-not (Test-Path "$absolute\postgres.dump")) { throw 'PostgreSQL backup copy failed.' }

# --- 2. MinIO bucket export ---
$minioContainer = (docker @compose ps -q minio).Trim()
if (-not $minioContainer) { throw 'MinIO container is not running.' }
Write-Output "[2/4] 导出 MinIO 对象..."
$minioDir = Join-Path $absolute 'minio'
New-Item -ItemType Directory -Force $minioDir | Out-Null
docker exec $minioContainer sh -c 'cd /data && tar cf /tmp/minio-backup.tar .'
if ($LASTEXITCODE -ne 0) { throw 'MinIO tar failed.' }
docker cp "${minioContainer}:/tmp/minio-backup.tar" "$minioDir\objects.tar"
docker exec $minioContainer rm -f /tmp/minio-backup.tar | Out-Null
if (-not (Test-Path "$minioDir\objects.tar")) { throw 'MinIO backup copy failed.' }

# --- 3. Manifest ---
Write-Output "[3/4] 生成 manifest..."
$pgSize = (Get-Item "$absolute\postgres.dump").Length
$minioSize = (Get-Item "$minioDir\objects.tar").Length
$manifest = @{
  created_at = (Get-Date).ToUniversalTime().ToString('o')
  postgres_dump_size = $pgSize
  minio_archive_size = $minioSize
  format_version = 2
} | ConvertTo-Json
$manifest | Set-Content "$absolute\manifest.json" -Encoding UTF8

# --- 4. Checksums ---
Write-Output "[4/4] 计算 SHA-256 校验和..."
$checksums = @()
foreach ($file in @("$absolute\postgres.dump", "$minioDir\objects.tar")) {
  $hash = (Get-FileHash $file -Algorithm SHA256).Hash
  $name = [IO.Path]::GetRelativePath($absolute, $file)
  $checksums += "$hash  $name"
}
$checksums -join "`n" | Set-Content "$absolute\checksums.sha256" -Encoding UTF8

Write-Output "备份完成: $absolute"
Write-Output "  postgres.dump  $([math]::Round($pgSize/1MB, 2)) MB"
Write-Output "  minio/objects.tar  $([math]::Round($minioSize/1MB, 2)) MB"
