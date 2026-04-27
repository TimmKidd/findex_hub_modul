# MAIN CONTOUR RUNBOOK — FindexHub

## Канонический MAIN contour

### Docker Compose project name
findex-prod

### Compose file
deploy/docker-compose.server.yml

### Main env file
deploy/main.env

### Текущий статус
MAIN contour пока не переведён полностью в dockerized runtime model.
На текущий момент исторически подтверждено следующее:

- MAIN infra существует в Docker:
  - `findex_pg`
  - `findex_redis`

- legacy app runtime historically существовал через:
  - `supervisord.conf`
  - `main.py`
  - `python -m findex_bot.jobs`
  - `support_bot/support_bot.py`

- по audit установлено, что supervisord сейчас не активен и не должен считаться канонической runtime-моделью.

---

## Каноническое направление для MAIN

Целевая MAIN runtime-модель:

- postgres (docker)
- redis (docker)
- bot (docker)
- jobs (docker)
- resurrection (docker)
- support (docker)

MAIN должен быть приведён к той же runtime-модели, что и TEST,
но со своими:
- env
- токенами
- chat/channel ids
- db/redis namespace
- compose project name

---

## Канонические команды MAIN

### Поднять MAIN
docker compose -p findex-prod -f deploy/docker-compose.server.yml --env-file deploy/main.env up -d

### Остановить MAIN
docker compose -p findex-prod -f deploy/docker-compose.server.yml --env-file deploy/main.env down

### Пересобрать MAIN
docker compose -p findex-prod -f deploy/docker-compose.server.yml --env-file deploy/main.env build --no-cache

### Проверить состояние MAIN
docker compose -p findex-prod -f deploy/docker-compose.server.yml --env-file deploy/main.env ps

### Логи MAIN main bot
docker compose -p findex-prod -f deploy/docker-compose.server.yml --env-file deploy/main.env logs --tail 100 bot

### Логи MAIN support bot
docker compose -p findex-prod -f deploy/docker-compose.server.yml --env-file deploy/main.env logs --tail 100 support

### Логи MAIN jobs
docker compose -p findex-prod -f deploy/docker-compose.server.yml --env-file deploy/main.env logs --tail 100 jobs

### Логи MAIN resurrection
docker compose -p findex-prod -f deploy/docker-compose.server.yml --env-file deploy/main.env logs --tail 100 resurrection

---

## ВАЖНО

### Запрещено
Не поднимать MAIN без фиксированного project name.

### Нельзя использовать
- docker compose up -d без `-p`
- project name `findex`
- project name `deploy`
- любой другой произвольный namespace

### Причина
Это может создать второй параллельный MAIN contour и привести к:
- дублированию контейнеров
- TelegramConflictError
- конфликту с TEST
- путанице с postgres/redis/runtime

---

## Историческая заметка

### Supervisord
Считать legacy runtime layer.

Он использовался исторически, но по audit установлено:
- `supervisord` сейчас не активен
- `supervisorctl` не подключается к socket
- historical logs фиксируют repeated crashes `findex_main`
- зафиксированы import errors:
  - `ModuleNotFoundError: No module named 'findex_bot.db.repo'`
  - `No module named findex_bot.jobs`

### Следствие
Supervisord не использовать как основу будущей MAIN runtime-модели.

---

## Текущая MAIN infra

### PostgreSQL
- container: `findex_pg`
- db: `findex`

### Redis
- container: `findex_redis`

### Historical local MAIN env
By audit:
- DATABASE_URL -> `127.0.0.1:5433/findex`
- REDIS_HOST -> `127.0.0.1`
- REDIS_PORT -> `6379`

Это подтверждает, что старая MAIN-модель была hybrid:
- infra в Docker
- app-layer на хосте

---

## Цель следующего этапа

Подготовить `deploy/main.env` и безопасный план перевода MAIN
в dockerized contour без:
- второго MAIN мира
- конфликта с TEST
- конфликта polling
- конфликта базы/redis
- случайного переключения production runtime

---

## MAIN contour считается канонизированным только когда:

- существует `deploy/main.env`
- MAIN поднимается только через `findex-prod`
- MAIN runtime не зависит от supervisord
- MAIN и TEST разведены по project name
- MAIN и TEST разведены по env
- MAIN и TEST разведены по runtime-контейнерам