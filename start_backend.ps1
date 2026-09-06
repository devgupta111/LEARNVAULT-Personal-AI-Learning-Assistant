# ============================================================
#  start_backend.ps1
#  Run this from the project ROOT or from backend/ to start
#  the FastAPI backend server.
#
#  Usage:
#    Right-click → "Run with PowerShell"
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
if (-not (Test-Path ".venv\Scripts\uvicorn.exe")) {
    Write-Host ""
    Write-Host "❌ Virtual environment not found." -ForegroundColor Red
    Write-Host "   Run these commands first:" -ForegroundColor Yellow
    Write-Host "     py -m venv .venv" -ForegroundColor Yellow
    Write-Host "     .venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    Write-Host "     pip install -r requirements.txt" -ForegroundColor Yellow
    Write-Host ""
    pause
    exit 1
}

Write-Host "✅ Virtual environment found" -ForegroundColor Green
Write-Host ""
Write-Host "🚀 Starting server at http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "📖 Swagger docs at http://127.0.0.1:8000/docs" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C to stop the server." -ForegroundColor Gray
Write-Host ""

# Start uvicorn with --reload for development
.venv\Scripts\uvicorn.exe app.main:app --reload
