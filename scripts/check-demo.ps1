param(
    [string]$Password = $env:SEED_PASSWORD,
    [switch]$Start,
    [switch]$Build
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $root
$script:passed = 0
$script:demoPassword = $Password
$envFile = @{}

if (Test-Path '.env') {
    foreach ($line in Get-Content '.env' -Encoding UTF8) {
        if ($line -match '^\s*([^#=\s]+)\s*=\s*(.*)\s*$') {
            $envFile[$matches[1]] = $matches[2].Trim().Trim('"').Trim("'")
        }
    }
}

function Get-ConfigValue([string]$Name, [string]$Default = '') {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ($value) { return $value }
    if ($envFile.ContainsKey($Name) -and $envFile[$Name]) { return $envFile[$Name] }
    return $Default
}

function Invoke-Native([scriptblock]$Command) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $Command 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) { throw ($output -join [Environment]::NewLine) }
    return $output
}

function Invoke-Check([string]$Name, [string]$Hint, [scriptblock]$Action) {
    Write-Host "`n==> $Name" -ForegroundColor Cyan
    try {
        & $Action
        $script:passed++
        Write-Host "[PASS] $Name" -ForegroundColor Green
    } catch {
        Write-Host "[FAIL] $Name" -ForegroundColor Red
        Write-Host ("原因：" + $_.Exception.Message) -ForegroundColor Yellow
        Write-Host ("建议：" + $Hint) -ForegroundColor Yellow
        exit 1
    }
}

Invoke-Check '环境变量' '复制 .env.example 为 .env，生成互不相同的强随机 POSTGRES_PASSWORD、JWT_SECRET、SERVICE_API_TOKEN 和 SEED_PASSWORD。' {
    $required = @('POSTGRES_PASSWORD', 'JWT_SECRET', 'SERVICE_API_TOKEN')
    foreach ($name in $required) {
        $value = Get-ConfigValue $name
        if (-not $value) { throw "$name 未设置" }
        [Environment]::SetEnvironmentVariable($name, $value)
    }
    if (-not $script:demoPassword) { $script:demoPassword = Get-ConfigValue 'SEED_PASSWORD' }
    if (-not $script:demoPassword -or $script:demoPassword.Length -lt 12) { throw 'SEED_PASSWORD 未设置或少于 12 个字符' }
    if ((Get-ConfigValue 'POSTGRES_PASSWORD').Length -lt 12) { throw 'POSTGRES_PASSWORD 少于 12 个字符' }
    if ((Get-ConfigValue 'JWT_SECRET').Length -lt 32) { throw 'JWT_SECRET 少于 32 个字符' }
    if ((Get-ConfigValue 'SERVICE_API_TOKEN').Length -lt 24) { throw 'SERVICE_API_TOKEN 少于 24 个字符' }
    $values = @((Get-ConfigValue 'POSTGRES_PASSWORD'), (Get-ConfigValue 'JWT_SECRET'), (Get-ConfigValue 'SERVICE_API_TOKEN'), $script:demoPassword)
    if (($values | Select-Object -Unique).Count -ne 4) { throw '四个密钥必须互不相同' }
    $env:SEED_PASSWORD = $script:demoPassword
    $env:SEED_PROFILE = 'demo'
}

Invoke-Check 'Docker 服务' '启动 Docker Desktop；执行 docker compose logs --tail=200 查看失败服务。端口冲突时调整 .env 中的宿主机端口。' {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw '找不到 docker 命令' }
    Invoke-Native { docker info --format '{{.ServerVersion}}' } | Out-Null
    Invoke-Native { docker compose version } | Out-Null
    Invoke-Native { docker compose config -q } | Out-Null
    if ($Start) {
        $dockerArgs = @('compose', 'up', '-d', '--wait')
        if ($Build) { $dockerArgs += '--build' }
        Invoke-Native { & docker $dockerArgs } | Out-Null
    }
    $rows = @(Invoke-Native { docker compose ps --format json } | ForEach-Object { $_ | ConvertFrom-Json })
    $expected = @('frontend', 'postgres', 'minio', 'backend', 'duckling', 'action_server', 'rasa', 'worker')
    foreach ($service in $expected) {
        $row = $rows | Where-Object { $_.Service -eq $service }
        if (-not $row) { throw "$service 未运行；可加 -Start -Build 自动构建启动" }
        if ($row.State -ne 'running' -or $row.Health -ne 'healthy') { throw "$service 状态为 $($row.Status)" }
    }
}

Invoke-Check '数据库迁移' '执行 docker compose exec -T backend alembic upgrade head；若失败，检查 DATABASE_URL 与 PostgreSQL 日志。' {
    Invoke-Native { docker compose exec -T backend alembic check } | Out-Null
    $migration = (Invoke-Native { docker compose exec -T backend alembic current }) -join ' '
    if ($migration -notmatch '0011' -or $migration -notmatch 'head') { throw "迁移版本不是 0011 head：$migration" }
}

Invoke-Check 'Seed 数据' '确认 SEED_PASSWORD 合规，并执行 docker compose exec -T -e SEED_PASSWORD -e SEED_PROFILE=demo backend python -m app.seed。' {
    $seed = (Invoke-Native { docker compose exec -T -e SEED_PASSWORD -e SEED_PROFILE backend python -m app.seed }) -join ' '
    if ($seed -notmatch 'Seed 完成') { throw "Seed 未返回成功标记：$seed" }
}

$backendPort = Get-ConfigValue 'BACKEND_PORT' '8001'
$rasaPort = Get-ConfigValue 'RASA_PORT' '5005'
$frontendPort = Get-ConfigValue 'FRONTEND_PORT' '8080'
$backendUrl = "http://127.0.0.1:$backendPort"
$rasaUrl = "http://127.0.0.1:$rasaPort"
$frontendUrl = "http://127.0.0.1:$frontendPort"

Invoke-Check '登录' '重新执行 Seed，并检查 backend 日志、账号 citizen_local 是否启用以及登录限流设置。' {
    $body = @{ username = 'citizen_local'; password = $script:demoPassword } | ConvertTo-Json
    $login = Invoke-RestMethod -Method Post -Uri "$backendUrl/api/v1/auth/login" -ContentType 'application/json' -Body $body -TimeoutSec 10
    if (-not $login.success -or -not $login.data.access_token) { throw '登录响应中没有 access_token' }
}

Invoke-Check 'Rasa' '检查 models/tingting-v1.1.0-rasa3.6.20.tar.gz、rasa/action_server/duckling 日志以及 ACTION_SERVER_URL、DUCKLING_URL。' {
    $status = Invoke-RestMethod -Uri "$rasaUrl/status" -TimeoutSec 10
    if (-not $status.model_file) { throw 'Rasa 未加载模型' }
    $sender = 'demo-check-' + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $greet = Invoke-RestMethod -Method Post -Uri "$rasaUrl/webhooks/rest/webhook" -ContentType 'application/json' -Body (@{ sender = $sender; message = '你好' } | ConvertTo-Json) -TimeoutSec 30
    if (@($greet).Count -lt 1) { throw 'Rasa 问候链路没有返回消息' }
    $queryMessage = '/query_request_status{"ticket_id":"QTDEMO000000000001"}'
    $query = Invoke-RestMethod -Method Post -Uri "$rasaUrl/webhooks/rest/webhook" -ContentType 'application/json' -Body (@{ sender = $sender; message = $queryMessage } | ConvertTo-Json) -TimeoutSec 30
    $queryText = (@($query) | ForEach-Object { $_.text }) -join ' '
    if ($queryText -notmatch 'QTDEMO000000000001') { throw 'Rasa → Action Server → Backend 工单查询链路未返回演示工单' }
}

Invoke-Check 'Backend' '查看 docker compose logs backend；确认 PostgreSQL healthy、JWT_SECRET 和数据库连接配置正确。' {
    $live = Invoke-RestMethod -Uri "$backendUrl/health/live" -TimeoutSec 10
    $ready = Invoke-RestMethod -Uri "$backendUrl/health/ready" -TimeoutSec 10
    if (-not $live.success -or $live.data.status -ne 'alive' -or -not $ready.success -or $ready.data.status -ne 'ready') { throw 'Backend live/ready 状态异常' }
}

Invoke-Check '健康检查' '执行 docker compose ps 和 docker compose logs --tail=200；确认前端端口未冲突。' {
    $frontendHealth = Invoke-WebRequest -UseBasicParsing -Uri "$frontendUrl/healthz" -TimeoutSec 10
    if ($frontendHealth.StatusCode -ne 200) { throw "Frontend healthz 返回 $($frontendHealth.StatusCode)" }
    $unhealthy = @(Invoke-Native { docker compose ps --format json } | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.Health -ne 'healthy' })
    if ($unhealthy.Count -gt 0) { throw (($unhealthy | ForEach-Object { "$($_.Service)=$($_.Status)" }) -join ', ') }
}

Write-Host "`n演示检查完成：$script:passed/8 项通过，八服务 healthy。" -ForegroundColor Green
Write-Host "Web: $frontendUrl  Backend: $backendUrl/docs  Rasa: $rasaUrl/status"
