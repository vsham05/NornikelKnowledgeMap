# Start infrastructure + backend (PowerShell)

Write-Host "Starting Docker services (Neo4j, Qdrant, MinIO)..." -ForegroundColor Cyan
docker compose up -d

Write-Host "Waiting for services..." -ForegroundColor Yellow
Start-Sleep -Seconds 15

Write-Host "Starting FastAPI backend on :8000..." -ForegroundColor Cyan
Set-Location nornikel-backend
$env:PYTHONPATH = "src"
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    .\.venv\Scripts\pip install -e .
}
.\.venv\Scripts\python run.py
