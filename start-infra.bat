@echo off
cd /d "%~dp0"
echo Starting Neo4j, Qdrant, and MinIO (docker compose)...
docker compose up -d
if errorlevel 1 (
  echo Failed to start Docker services. Is Docker Desktop running?
  exit /b 1
)
echo Infrastructure containers started.
