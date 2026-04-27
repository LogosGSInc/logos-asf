# LOGOS ASF — Windows one-click start (PowerShell)
# Usage:  Right-click → "Run with PowerShell"
#  or:    pwsh -ExecutionPolicy Bypass -File start.ps1

$ErrorActionPreference = "Stop"
Write-Host ""
Write-Host "──────────────────────────────────────────────────"
Write-Host "  LOGOS ASF — Sprint 5 deploy (Windows)"
Write-Host "──────────────────────────────────────────────────"
Write-Host ""

# Verify Docker is available
try {
    docker --version | Out-Null
} catch {
    Write-Host "[ERROR] Docker Desktop not found. Install from https://www.docker.com/products/docker-desktop/"
    Read-Host "Press Enter to exit"
    exit 1
}

# Verify .abigail.env exists
if (-not (Test-Path ".abigail.env")) {
    Write-Host "[WARN] .abigail.env not found in repo root."
    Write-Host "       Abigail will start in offline (no-LLM) mode."
    Write-Host "       Create .abigail.env with: GROQ_API_KEY=..."
    Write-Host ""
}

Write-Host "→ Starting containers..."
docker compose up --build -d

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] docker compose failed. Check Docker Desktop is running."
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "✓ Stack is up."
Write-Host ""
Write-Host "  Operator Console : http://localhost:7070/dashboard"
Write-Host "  Intent Compiler  : http://localhost:7070/intake"
Write-Host "  Sentinel health  : http://localhost:9090/health"
Write-Host ""
Write-Host "  Logs:  docker compose logs -f"
Write-Host "  Stop:  docker compose down"
Write-Host ""

Start-Sleep -Seconds 2
Start-Process "http://localhost:7070/dashboard"
