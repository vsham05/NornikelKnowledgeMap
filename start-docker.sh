#!/usr/bin/env bash
# Start the full Docker stack (Linux / macOS). Windows: use start-docker.bat
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.yaml --env-file .env.docker)

if [[ ! -f .env.docker ]]; then
  echo "Creating .env.docker from .env.example ..."
  cp .env.example .env.docker
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found. Install Docker Engine or Docker Desktop."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker daemon is not running. Start Docker and retry."
  exit 1
fi

gpu_ok=0

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "ERROR: nvidia-smi not found. Install NVIDIA drivers before starting the stack."
  exit 1
fi

if docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi >/dev/null 2>&1; then
  gpu_ok=1
fi

if [[ "$gpu_ok" -ne 1 ]]; then
  echo "ERROR: Docker cannot access the NVIDIA GPU."
  echo ""
  echo "Linux (Ubuntu/Debian):"
  echo "  sudo apt install -y nvidia-container-toolkit"
  echo "  sudo nvidia-ctk runtime configure --runtime=docker"
  echo "  sudo systemctl restart docker"
  echo ""
  echo "See README.md → GPU (Linux) for details."
  exit 1
fi

echo "Starting full stack in Docker (NVIDIA GPU required for Ollama) ..."
echo "Neo4j, Qdrant, MinIO, Ollama, backend, frontend"
echo "First run downloads Ollama models (~10 GB) — may take 10–30 minutes."
echo "Watch progress: docker compose logs -f ollama-pull"
echo

"${COMPOSE[@]}" up -d --build --remove-orphans

echo
echo "Stack starting. When ollama-pull finishes and backend is up:"
echo "  App:   http://localhost:3000"
echo "  API:   http://localhost:8000/docs"
echo "  Neo4j: http://localhost:7474  (neo4j / password123)"
echo "  MinIO: http://localhost:9001  (minioadmin / minioadmin)"
echo "  GPU:   docker exec skg-ollama ollama ps  (must show GPU, never CPU)"
echo
echo "Verifying Ollama GPU-only mode ..."
"${COMPOSE[@]}" run --rm --no-deps --entrypoint /bin/sh ollama-pull \
  -c "sh /patch-gpu.sh && sh /verify-gpu.sh"
echo "GPU-only verification passed."
