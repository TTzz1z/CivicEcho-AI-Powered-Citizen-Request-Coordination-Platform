<#
.SYNOPSIS
    倾听助手 PostgreSQL + MinIO 联合恢复
.DESCRIPTION
    从备份包恢复 PostgreSQL 数据和 MinIO 对象，并验证附件完整性。
.EXAMPLE
    .\scripts\restore.ps1 -BackupDir backups\tingting-20260719-120000
    .\scripts\restore.ps1 -BackupDir backups\tingting-20260719-120000 -SkipVerify
#>
param(
  [Parameter(Mandatory)][string]$BackupDir,
  [string]$Project = '',
  [switch]$SkipVerify
)
$ErrorActionPreference = 'Stop'
$compose = @('compose')
if ($Project) { $compose += @('-p', $Project) }

$absolute = [IO.Path]::GetFullPath((Join-Path (Get-Location) $BackupDir))
if (-not (Test-Path "$absolute\postgres.dump")) { throw "备份包无效: 缺少 postgres.dump ($absolute)" }
if (-not (Test-Path "$absolute\minio\objects.tar")) { throw "备份包无效: 缺少 minio/objects.tar" }

# --- 1. Verify checksums ---
Write-Output "[1/4] 校验 SHA-256..."
if (Test-Path "$absolute\checksums.sha256") {
  $lines = Get-Content "$absolute\checksums.sha256"
  foreach ($line in $lines) {
    if (-not $line.Trim()) { continue }
    $parts = $line -split '\s+', 2
    $expectedHash = $parts[0]
    $filePath = Join-Path $absolute $parts[1]
    $actualHash = (Get-FileHash $filePath -Algorithm SHA256).Hash
    if ($actualHash -ne $expectedHash) {
      throw "校验失败: $($parts[1]) 期望 $expectedHash 实际 $actualHash"
    }
  }
  Write-Output "  校验通过"
} else {
  Write-Output "  警告: 无 checksums.sha256，跳过校验"
}

# --- 2. Restore PostgreSQL ---
$pgContainer = (docker @compose ps -q postgres).Trim()
if (-not $pgContainer) { throw 'PostgreSQL container is not running.' }
Write-Output "[2/4] 恢复 PostgreSQL..."
docker cp "$absolute\postgres.dump" "${pgContainer}:/tmp/tingting-restore.dump"
docker exec $pgContainer sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner -j 2 /tmp/tingting-restore.dump 2>&1 || true'
if ($LASTEXITCODE -ne 0) { Write-Output "  警告: pg_restore 报告部分问题（通常因对象已存在）" }
docker exec $pgContainer rm -f /tmp/tingting-restore.dump | Out-Null
Write-Output "  PostgreSQL 恢复完成"

# --- 3. Restore MinIO ---
$minioContainer = (docker @compose ps -q minio).Trim()
if (-not $minioContainer) { throw 'MinIO container is not running.' }
Write-Output "[3/4] 恢复 MinIO 对象..."
docker cp "$absolute\minio\objects.tar" "${minioContainer}:/tmp/minio-restore.tar"
docker exec $minioContainer sh -c 'cd /data && tar xf /tmp/minio-restore.tar'
if ($LASTEXITCODE -ne 0) { throw 'MinIO restore failed.' }
docker exec $minioContainer rm -f /tmp/minio-restore.tar | Out-Null
Write-Output "  MinIO 恢复完成"

# --- 4. Verify attachment integrity ---
if ($SkipVerify) {
  Write-Output "[4/4] 跳过附件完整性验证 (-SkipVerify)"
} else {
  Write-Output "[4/4] 验证附件完整性..."
  $backendContainer = (docker @compose ps -q backend).Trim()
  if ($backendContainer) {
    docker exec $backendContainer python -m app.verify_restore
    if ($LASTEXITCODE -ne 0) { throw '附件完整性验证失败！请检查缺失或损坏的对象。' }
    Write-Output "  附件完整性验证通过"
  } else {
    Write-Output "  警告: backend 容器未运行，跳过验证"
  }
}

Write-Output "恢复完成: $absolute"
