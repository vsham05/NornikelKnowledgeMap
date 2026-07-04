@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
rem Windows launcher — Linux/macOS: ./start-docker.sh

if not exist .env.docker (
  echo Creating .env.docker from .env.example ...
  copy /Y .env.example .env.docker >nul
)

set "GPU_OK=0"

where nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo ERROR: nvidia-smi not found. Install NVIDIA drivers before starting the stack.
  exit /b 1
)

docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi >nul 2>&1
if not errorlevel 1 set "GPU_OK=1"

if "!GPU_OK!"=="0" (
  echo ERROR: Docker cannot access the NVIDIA GPU.
  echo Enable GPU in Docker Desktop: Settings - Resources - GPU
  echo Then install/update the NVIDIA Container Toolkit if needed.
  exit /b 1
)

echo Starting full stack in Docker ^(NVIDIA GPU required for Ollama^) ...
echo Neo4j, Qdrant, MinIO, Ollama, backend, frontend
echo First run downloads Ollama models (~10 GB) — may take 10-30 minutes.
echo Watch progress: docker compose logs -f ollama-pull
echo.

docker compose -f docker-compose.yaml --env-file .env.docker up -d --build --remove-orphans
if errorlevel 1 (
  echo Docker compose failed. Is Docker Desktop running with GPU enabled?
  exit /b 1
)

echo.
echo Stack starting. When ollama-pull finishes and backend is up:
echo   App:   http://localhost:3000
echo   API:   http://localhost:8000/docs
echo   Neo4j: http://localhost:7474  (neo4j / password123)
echo   MinIO: http://localhost:9001  (minioadmin / minioadmin)
echo   GPU:   docker exec skg-ollama ollama ps  ^(must show GPU, never CPU^)
echo.
echo Verifying Ollama GPU-only mode ...
docker compose -f docker-compose.yaml --env-file .env.docker run --rm --no-deps --entrypoint /bin/sh ollama-pull -c "sh /patch-gpu.sh && sh /verify-gpu.sh"
if errorlevel 1 (
  echo ERROR: Ollama is not running GPU-only. Fix Docker GPU settings and retry.
  exit /b 1
)
echo GPU-only verification passed.
