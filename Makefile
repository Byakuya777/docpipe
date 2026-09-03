.PHONY: up down logs ps migrate revision

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

migrate:
	docker compose exec backend alembic upgrade head

# usage: make revision m="add batch table"
revision:
	docker compose exec backend alembic revision --autogenerate -m "$(m)"
