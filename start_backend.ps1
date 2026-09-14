# ============================================================
#  start_backend.ps1
#  Run this from the project ROOT or from backend/ to start
#  the FastAPI backend server.
#
#  Usage:
#    Right-click -> "Run with PowerShell"
#    OR in terminal: .\start_backend.ps1
# ============================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Personal AI Learning Assistant" -ForegroundColor Cyan
Write-Host "  Starting Backend (FastAPI)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Navigate to backend/ regardless of where the script is run from
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $scriptDir "backend"

if (-not (Test-Path $backendDir)) {
    # Maybe script is already inside backend/
    $backendDir = $scriptDir
}

Set-Location $backendDir
Write-Host "Working directory: $backendDir" -ForegroundColor Gray

# Check venv exists
$pythonExe = Join-Path $backendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    Write-Host ""
    Write-Host "Virtual environment not found in .venv." -ForegroundColor Red
    Write-Host "   Run these commands first:" -ForegroundColor Yellow
    Write-Host "     py -m venv .venv" -ForegroundColor Yellow
    Write-Host "     .venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    Write-Host "     pip install -r requirements.txt" -ForegroundColor Yellow
    Write-Host ""
    pause
    exit 1
}

Write-Host "Virtual environment found" -ForegroundColor Green

# Set PYTHONPATH to current backend directory for clean imports
$env:PYTHONPATH = "."

# Check if port 8000 is currently occupied
$portCheck = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
if ($portCheck) {
    Write-Host "Notice: Port 8000 is currently in use (PID: $($portCheck[0].OwningProcess))." -ForegroundColor Yellow
    Write-Host "If a previous backend server is still running, stop it with Ctrl+C or kill the process." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Starting FastAPI backend server..." -ForegroundColor Green
Write-Host "  Backend API:  http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "  Swagger Docs: http://127.0.0.1:8000/docs" -ForegroundColor Green
Write-Host "  Health Check: http://127.0.0.1:8000/health" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C to stop the server." -ForegroundColor Gray
Write-Host ""

# Run uvicorn with reload and explicit host/port
& $pythonExe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
