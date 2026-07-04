@echo off
cd /d "%~dp0"

if not exist .env.docker (
  echo Creating .env.docker from .env.example ...
  copy /Y .env.example .env.docker >nul
)

echo Starting full stack in Docker (Neo4j, Qdrant, MinIO, Ollama, backend, frontend)...
echo First run downloads Ollama models (~10 GB) — may take 10-30 minutes.
echo Watch progress: docker compose logs -f ollama-pull
echo.

docker compose --env-file .env.docker up -d --build --remove-orphans
if errorlevel 1 (
  echo Docker compose failed. Is Docker Desktop running?
  exit /b 1
)

echo.
echo Stack starting. When ollama-pull finishes and backend is up:
echo   App:   http://localhost:3000
echo   API:   http://localhost:8000/docs
echo   Neo4j: http://localhost:7474  (neo4j / password123)
echo   MinIO: http://localhost:9001  (minioadmin / minioadmin)
