FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY app ./app
COPY alembic.ini .
COPY alembic ./alembic

RUN pip install --no-cache-dir .

# Bind 0.0.0.0 and use the PORT Railway injects; the fallback keeps the image
# runnable on its own and under docker-compose.
#
# `--host ::` is NOT a dual-stack shortcut. asyncio sets IPV6_V6ONLY on the
# listening socket regardless of net.ipv6.bindv6only, so a :: bind refuses IPv4
# outright — measured in this image: it answered on [::1] and refused
# 127.0.0.1. Railway environments created before 2025-10-16 have IPv6-only
# private networking and do need ::; DEPLOY.md covers that case.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
