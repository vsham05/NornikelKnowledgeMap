@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if not exist .env.docker (
  echo Creating .env.docker from .env.example ...
  copy /Y .env.example .env.docker >nul
)

echo.
echo [1/2] Checking Ollama on your PC (localhost:11434)...
powershell -NoProfile -Command ^
  "try { Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' -UseBasicParsing -TimeoutSec 5 | Out-Null; exit 0 } " ^
  "catch { Write-Host 'Ollama is not running.' -ForegroundColor Red; exit 1 }"
if errorlevel 1 (
  echo.
  echo Install Ollama for Windows: https://ollama.com/download
  echo Start the Ollama app, then pull models:
  echo   ollama pull qwen2.5:7b-instruct
  echo   ollama pull mxbai-embed-large
  echo   ollama pull minicpm-v
  exit /b 1
)

set MISSING=
for %%M in (qwen2.5:7b-instruct mxbai-embed-large minicpm-v) do (
  ollama show %%M >nul 2>&1
  if errorlevel 1 set MISSING=!MISSING! %%M
)
if defined MISSING (
  echo.
  echo Missing models:%MISSING%
  echo Pull them in a terminal, then re-run start-docker.bat:
  echo   ollama pull qwen2.5:7b-instruct
  echo   ollama pull mxbai-embed-large
  echo   ollama pull minicpm-v
  exit /b 1
)
echo Ollama OK.

echo.
echo [2/2] Starting Docker stack (Neo4j, Qdrant, MinIO, backend, frontend)...
docker compose --env-file .env.docker up -d --build
if errorlevel 1 (
  echo Docker compose failed. Is Docker Desktop running?
  exit /b 1
)

echo.
echo Ready:
echo   App:   http://localhost:3000
echo   API:   http://localhost:8000/docs
echo   Neo4j: http://localhost:7474  (neo4j / password123)
echo   MinIO: http://localhost:9001  (minioadmin / minioadmin)
