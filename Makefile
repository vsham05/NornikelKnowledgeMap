# Cross-platform shortcuts (Linux / macOS). Windows: use start-docker.bat
.PHONY: up down logs rebuild-backend restart-backend verify-gpu env help

COMPOSE = docker compose -f docker-compose.yaml --env-file .env.docker

help:
	@echo "Targets:"
	@echo "  make up              Start full stack (./start-docker.sh)"
	@echo "  make down            Stop containers (keep data)"
	@echo "  make logs            Follow backend logs"
	@echo "  make rebuild-backend Rebuild and restart API only"
	@echo "  make restart-backend Restart API container (no rebuild)"
	@echo "  make verify-gpu      Check Ollama GPU inference"
	@echo "  make env             Create .env.docker from .env.example"

env:
	@test -f .env.docker || cp .env.example .env.docker
	@echo ".env.docker ready"

up: env
	@chmod +x start-docker.sh scripts/*.sh 2>/dev/null || true
	./start-docker.sh

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f backend

rebuild-backend:
	$(COMPOSE) up -d --no-deps --build backend

restart-backend:
	$(COMPOSE) restart backend

verify-gpu:
	$(COMPOSE) run --rm --no-deps --entrypoint /bin/sh ollama-pull \
		-c "sh /verify-gpu.sh"
