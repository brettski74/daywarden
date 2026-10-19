# Local stack. The listen port and the CA directory come from .env.

.PHONY: up down

up:
	set -a && . ./.env && set +a && mkdir -p "$$CA_VOLUME_PATH" && docker compose up -d --wait

down:
	docker compose down
