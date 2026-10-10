[CmdletBinding()]
param(
    [string]$OpenWeatherApiKey = $env:OPENWEATHER_API_KEY,
    [string]$DemoJwtSecret = $env:DEMO_JWT_SECRET
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$web = Join-Path $root "web"
$python = Join-Path $backend ".venv\Scripts\python.exe"

function Stop-WithMessage([string]$message) {
    Write-Host "`n錯誤：$message" -ForegroundColor Red
    exit 1
}

Write-Host "RunSense 啟動準備中..." -ForegroundColor Cyan

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Stop-WithMessage "找不到 Python Launcher (py)。請安裝 Python 3.11 或更新版本。"
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Stop-WithMessage "找不到 Node.js。請先安裝 Node.js。"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Stop-WithMessage "找不到 npm。請確認 Node.js 已正確安裝。"
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Stop-WithMessage "找不到 Docker。請啟動 Docker Desktop。"
}

if (-not (Test-Path $python)) {
    Write-Host "建立 Python 3.11 虛擬環境..." -ForegroundColor Yellow
    py -3.11 -m venv (Join-Path $backend ".venv")
}

Write-Host "安裝／更新後端依賴..." -ForegroundColor Yellow
Push-Location $backend
try {
    & $python -m pip install -e ".[dev]"
    Write-Host "啟動 PostgreSQL..." -ForegroundColor Yellow
    docker compose up -d

    $env:DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/runsense"
    $env:COMPETITION_DEMO_ONLY = "true"
    $env:CORS_ALLOWED_ORIGINS = "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174"
    if ([string]::IsNullOrWhiteSpace($DemoJwtSecret)) {
        $DemoJwtSecret = "runsense-local-demo-secret-2026"
    }
    $env:DEMO_JWT_SECRET = $DemoJwtSecret
    if (-not [string]::IsNullOrWhiteSpace($OpenWeatherApiKey)) {
        $env:OPENWEATHER_API_KEY = $OpenWeatherApiKey
    }

    Write-Host "執行資料庫 migration..." -ForegroundColor Yellow
    & $python -m alembic upgrade head
    Write-Host "建立 Demo 資料..." -ForegroundColor Yellow
    & $python scripts\seed_demo_personas.py
} finally {
    Pop-Location
}

if (-not (Test-Path (Join-Path $web "node_modules"))) {
    Write-Host "安裝前端依賴..." -ForegroundColor Yellow
    Push-Location $web
    try { npm install } finally { Pop-Location }
}

Write-Host "建置前端正式版..." -ForegroundColor Yellow
# the build bakes in the API base: /api goes through the same server (proxy),
# so the app works on localhost, on the LAN and through the public link alike
$env:VITE_API_BASE_URL = '/api'
Push-Location $web
try { npm run build } finally { Pop-Location }

$backendCommand = @"
Set-Location '$backend'
`$env:DATABASE_URL='$($env:DATABASE_URL)'
`$env:COMPETITION_DEMO_ONLY='true'
`$env:DEMO_JWT_SECRET='$($env:DEMO_JWT_SECRET)'
`$env:CORS_ALLOWED_ORIGINS='$($env:CORS_ALLOWED_ORIGINS)'
$(if (-not [string]::IsNullOrWhiteSpace($env:OPENWEATHER_API_KEY)) { "`$env:OPENWEATHER_API_KEY='$($env:OPENWEATHER_API_KEY)'" })
& '$python' -m uvicorn app.main:app --reload --port 8000
"@

$frontendCommand = @"
Set-Location '$web'
`$env:VITE_API_BASE_URL='/api'
npm run dev
"@

# production build for the phone / public link (Tailscale Funnel points here)
$previewCommand = @"
Set-Location '$web'
npx vite preview --port 4173 --strictPort
"@

Write-Host "開啟後端與前端服務視窗..." -ForegroundColor Green
Start-Process powershell.exe -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $backendCommand
Start-Process powershell.exe -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $frontendCommand
Start-Process powershell.exe -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $previewCommand

Start-Process "http://localhost:5173"
Write-Host "`nRunSense 已啟動。網站：http://localhost:5173  |  API 文件：http://127.0.0.1:8000/docs" -ForegroundColor Green
# only adapters with a gateway (the real Wi-Fi / hotspot), not WSL/VMware/VPN ones
$lanIps = Get-NetIPConfiguration -ErrorAction SilentlyContinue |
    Where-Object { $_.IPv4DefaultGateway } |
    ForEach-Object { $_.IPv4Address.IPAddress }
foreach ($ip in $lanIps) {
    Write-Host "手機（同一個 Wi-Fi／熱點）：http://$($ip):5173" -ForegroundColor Cyan
}
# the public link only exists if Funnel was turned on (tailscale funnel --bg 4173)
$funnel = ''
if (Get-Command tailscale -ErrorAction SilentlyContinue) {
    $funnel = (tailscale funnel status 2>$null | Select-String -Pattern '^https://\S+' | Select-Object -First 1).Matches.Value
}
if ($funnel) {
    Write-Host "公開網址（任何網路，手機與筆電共用）：$funnel" -ForegroundColor Cyan
} else {
    Write-Host "公開網址未開啟（需要時執行：tailscale funnel --bg 4173）" -ForegroundColor DarkGray
}
Write-Host "請保持新開的後端與前端視窗開啟；停止服務請在各視窗按 Ctrl+C。" -ForegroundColor DarkGray
