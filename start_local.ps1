# ClipFactory.ai — Local launcher (Windows)
# Usage:
#   .\start_local.ps1              (runs on port 8080)
#   .\start_local.ps1 -Port 8080
#   .\start_local.ps1 -Port 8000
param(
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"

$SCRIPT_DIR  = Split-Path -Parent $MyInvocation.MyCommand.Path
$FRONTEND_OUT = Join-Path $SCRIPT_DIR "frontend\out"
$INDEX_HTML   = Join-Path $FRONTEND_OUT "index.html"
$CONFIG_JS    = Join-Path $FRONTEND_OUT "_config.js"

# Inject API base URL dynamically for the chosen port
Set-Content -Path $CONFIG_JS -Value "window.__NEXT_PUBLIC_API_URL = 'http://localhost:$Port/api';" -Encoding UTF8

# Patch index.html to load _config.js (idempotent)
if (Test-Path $INDEX_HTML) {
    $html = Get-Content $INDEX_HTML -Raw -Encoding UTF8
    if ($html -notmatch "_config\.js") {
        $html = $html -replace "<head>", '<head><script src="/_config.js"></script>'
        Set-Content -Path $INDEX_HTML -Value $html -Encoding UTF8
        Write-Host "  Patched index.html to include _config.js" -ForegroundColor DarkGray
    }
}

# Free chosen port if an older instance is lingering on that port
try {
    $existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "  Freeing port $Port (PID $($existing.OwningProcess))..." -ForegroundColor DarkGray
        Stop-Process -Id $existing.OwningProcess -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 800
    }
} catch {}

Write-Host ""
Write-Host "  ClipFactory.ai - Local (Port $Port)" -ForegroundColor Cyan
Write-Host "  Dashboard : http://localhost:$Port" -ForegroundColor Green
Write-Host "  API       : http://localhost:$Port/api" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""

$env:PYTHONPATH   = $SCRIPT_DIR
$env:PYTHONUTF8   = "1"   # prevent emoji UnicodeEncodeError on Windows consoles
Set-Location $SCRIPT_DIR
python -m uvicorn server.main:app --host 127.0.0.1 --port $Port
