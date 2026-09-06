# ============================================================
#  start_frontend.ps1
#  Run this from the project ROOT or from frontend/ to start
#  the Next.js frontend dev server.
#
#  Usage:
#    Right-click → "Run with PowerShell"
#    OR in terminal: .\start_frontend.ps1
# ============================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "  Personal AI Learning Assistant" -ForegroundColor Magenta
Write-Host "  Starting Frontend (Next.js)" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""

# Navigate to frontend/ regardless of where the script is run from
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendDir = Join-Path $scriptDir "frontend"

if (-not (Test-Path $frontendDir)) {
    # Maybe script is already inside frontend/
    $frontendDir = $scriptDir
}

Set-Location $frontendDir
Write-Host "Working directory: $frontendDir" -ForegroundColor Gray

# Check node_modules exists
if (-not (Test-Path "node_modules")) {
    Write-Host ""
    Write-Host "❌ node_modules not found. Installing dependencies..." -ForegroundColor Yellow
    npm install
}

Write-Host ""
Write-Host "✅ Dependencies found" -ForegroundColor Green
Write-Host ""
Write-Host "🚀 Starting frontend at http://localhost:3000" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C to stop the server." -ForegroundColor Gray
Write-Host ""

npm run dev
