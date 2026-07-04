#!/usr/bin/env bash
# Fast backend-only rebuild/restart after code changes (no full stack restart).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.yaml --env-file .env.docker)

if [[ ! -f .env.docker ]]; then
  echo "Missing .env.docker — run ./start-docker.sh first or: cp .env.example .env.docker"
  exit 1
fi

echo "Rebuilding backend ..."
"${COMPOSE[@]}" up -d --no-deps --build backend
echo "Backend restarted — API: http://localhost:8000/docs"
