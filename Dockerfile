# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# системные зависимости (минимум, но достаточно для asyncpg/psycopg и т.п.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
  && rm -rf /var/lib/apt/lists/*

# если есть requirements.txt — используем его
# если его нет, сборка упадёт и ты сразу увидишь, что нужно сделать дальше
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# копируем проект
COPY . /app

# дефолтная команда (перекрывается в docker-compose.yml)
CMD ["python", "-c", "print('Container is ready')"]