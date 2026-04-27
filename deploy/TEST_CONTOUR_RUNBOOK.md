# TEST CONTOUR RUNBOOK — FindexHub

## Канонический TEST contour

### Docker Compose project name
findex-local-test

### Compose file
deploy/docker-compose.server.yml

### Env file
deploy/local.test.env

---

## Канонические идентификаторы TEST

### PostgreSQL database
findex_test_local

### Redis logical environment suffix
test_local

### Redis lock keys
POLLING_LOCK_KEY=findexhub:polling_lock:test_local  
JOBS_LEADER_KEY=jobs:leader:findexhub:test_local  
RES_WORKER_LEADER_KEY=resurrection:leader:findexhub:test_local

---

## Канонические сервисы TEST

- bot
- support
- jobs
- resurrection
- postgres
- redis

---

## Канонические команды TEST

### Поднять TEST
docker compose -p findex-local-test -f deploy/docker-compose.server.yml --env-file deploy/local.test.env up -d

### Остановить TEST
docker compose -p findex-local-test -f deploy/docker-compose.server.yml --env-file deploy/local.test.env down

### Пересобрать TEST
docker compose -p findex-local-test -f deploy/docker-compose.server.yml --env-file deploy/local.test.env build --no-cache

### Проверить состояние TEST
docker compose -p findex-local-test -f deploy/docker-compose.server.yml --env-file deploy/local.test.env ps

### Логи TEST main bot
docker compose -p findex-local-test -f deploy/docker-compose.server.yml --env-file deploy/local.test.env logs --tail 100 bot

### Логи TEST support bot
docker compose -p findex-local-test -f deploy/docker-compose.server.yml --env-file deploy/local.test.env logs --tail 100 support

### Логи TEST jobs
docker compose -p findex-local-test -f deploy/docker-compose.server.yml --env-file deploy/local.test.env logs --tail 100 jobs

### Логи TEST resurrection
docker compose -p findex-local-test -f deploy/docker-compose.server.yml --env-file deploy/local.test.env logs --tail 100 resurrection

---

## ВАЖНО

### Запрещено
Не поднимать TEST без фиксированного project name.

### Нельзя использовать
- docker compose up -d без `-p`
- произвольные project names вроде `deploy`, `findex_test`, `test_local`

### Причина
Это может создать второй параллельный TEST contour и привести к:
- дублированию контейнеров
- TelegramConflictError
- ложной диагностике
- путанице с PostgreSQL / Redis / polling

---

## Историческая заметка по responds schema

Старый TEST contour имел schema drift по таблице `responds`
относительно фактической MAIN schema.

### Что было вручную добавлено только в TEST
- owner_viewed_at
- owner_notified_at
- ping12_sent_at
- ping36_sent_at
- ping_owner24_sent_at

### Что было вручную добавлено только в TEST из индексов
- ix_responds_invited_at
- ix_responds_last_activity
- ix_responds_ping12_sent_at
- ix_responds_ping36_sent_at
- ix_responds_ping_owner24_sent_at

### Артефакты фикса
- deploy/manual_test_responds_patch.sql
- deploy/audit_snapshots/responds_patch_note.txt
- deploy/audit_snapshots/responds_main_reference.sql
- deploy/audit_snapshots/responds_test_after_patch.sql

### Важно
Этот patch был применён только к TEST.  
MAIN не изменялся.

---

## TEST contour считается рабочим, если

- публикация проходит
- deep-link работает
- кнопка "Откликнуться" работает
- сценарий mini-анкеты создаёт карточку отклика
- в логах нет DB-crash по `responds.owner_viewed_at`
- в Docker нет второго параллельного TEST contour