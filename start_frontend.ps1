# ============================================================
#  start_frontend.ps1
#  Run this from the project ROOT or from frontend/ to start
#  the Next.js frontend dev server.
#
#  Usage:
#    Right-click -> "Run with PowerShell"
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
    Write-Host "node_modules not found. Installing dependencies..." -ForegroundColor Yellow
    npm install
}

Write-Host "Dependencies found" -ForegroundColor Green

# Check if port 3000 is currently occupied
$portCheck = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue
if ($portCheck) {
    Write-Host "Notice: Port 3000 is currently in use (PID: $($portCheck[0].OwningProcess))." -ForegroundColor Yellow
    Write-Host "If a previous frontend server is still running, stop it with Ctrl+C or kill the process." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Starting Next.js frontend application..." -ForegroundColor Green
Write-Host "  Web App:    http://localhost:3000" -ForegroundColor Green
Write-Host "  Login Page: http://localhost:3000/login" -ForegroundColor Green
Write-Host "  Dashboard:  http://localhost:3000/dashboard" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C to stop the server." -ForegroundColor Gray
Write-Host ""

npm run dev
