# RUNTIME EVOLUTION NOTE — FindexHub

## Зачем этот файл

Этот документ фиксирует эволюцию runtime-модели проекта и нужен для того, чтобы:
- не путаться между старыми и новыми способами запуска
- понимать, какие слои считаются legacy
- не возвращаться случайно к устаревшей operational-модели
- иметь единое архитектурное объяснение перед дальнейшей миграцией на сервер

---

## История runtime-модели проекта

### Этап 1 — Supervisord
На раннем этапе проекта в качестве runtime-launcher использовался `supervisord`.

Для этого в проекте были созданы и использовались:
- `supervisord.conf`
- `run/supervisord.log`
- `run/main_bot.log`
- `run/main_bot_err.log`
- `run/findex_jobs.log`
- `run/findex_jobs_err.log`
- `run/support_bot.log`
- `run/support_bot_err.log`

`supervisord` запускал:
- `findex_main`
- `findex_jobs`
- `support_bot`

### Что показал аудит
По историческим логам установлено, что supervisor-слой реально использовался, но позднее стал нестабильным и broken:
- `findex_main` многократно падал
- supervisor переводил его в `FATAL state`
- в логах фиксировались ошибки импорта, включая:
  - `ModuleNotFoundError: No module named 'findex_bot.db.repo'`
  - `No module named findex_bot.jobs`

Это означает, что supervisord был не просто "старой идеей", а реально использовавшимся runtime-слоем, который со временем перестал быть надёжным.

---

### Этап 2 — Ручной запуск / restart.sh / run_all.sh
После проблем со supervisor-подходом проект перешёл к ручной operational-модели:
- ручные запуски
- `restart.sh`
- `run_all.sh`

Этот этап был переходным и позволял:
- быстрее диагностировать поведение проекта
- избегать части побочных эффектов supervisor
- вручную контролировать запуск bot / jobs / resurrection / support

Однако этот слой не стал каноническим long-term runtime standard.

---

### Этап 3 — Dockerized TEST contour
В рамках подготовки серверной миграции был стабилизирован отдельный TEST contour на Docker Compose.

Канонический TEST contour:
- Docker Compose project name: `findex-local-test`
- Compose file: `deploy/docker-compose.server.yml`
- Env file: `deploy/local.test.env`

Сервисы TEST:
- bot
- jobs
- resurrection
- support
- postgres
- redis

Именно этот TEST contour стал первым полноценно воспроизводимым и системно изолированным runtime-контуром проекта.

---

## Исторический инцидент: schema drift по responds в TEST

Во время диагностики отклика было установлено, что старый TEST contour имел schema drift по таблице `responds` относительно фактической MAIN schema.

### В TEST отсутствовали поля:
- `owner_viewed_at`
- `owner_notified_at`
- `ping12_sent_at`
- `ping36_sent_at`
- `ping_owner24_sent_at`

### В TEST отсутствовали индексы:
- `ix_responds_invited_at`
- `ix_responds_last_activity`
- `ix_responds_ping12_sent_at`
- `ix_responds_ping36_sent_at`
- `ix_responds_ping_owner24_sent_at`

Это вызывало runtime-crash в responds flow.

### Решение
Для старого TEST contour был применён ручной SQL patch только к TEST database.

Артефакты:
- `deploy/manual_test_responds_patch.sql`
- `deploy/audit_snapshots/responds_patch_note.txt`
- `deploy/audit_snapshots/responds_main_reference.sql`
- `deploy/audit_snapshots/responds_test_after_patch.sql`

MAIN database при этом не изменялась.

---

## Текущий архитектурный вывод

### Supervisord
Считать:
- legacy runtime layer
- deprecated operational layer
- неканоническим способом запуска проекта

### restart.sh / run_all.sh
Считать:
- переходным operational-слоем
- историческим способом ручного контроля
- нецелевым long-term standard

### Dockerized contour
Считать:
- каноническим направлением развития runtime-архитектуры
- базовой моделью для TEST
- целевым направлением и для MAIN

---

## Что считается каноническим направлением дальше

Целевая runtime-модель проекта:

### TEST
- postgres (docker)
- redis (docker)
- bot (docker)
- jobs (docker)
- resurrection (docker)
- support (docker)

### MAIN
- postgres (docker)
- redis (docker)
- bot (docker)
- jobs (docker)
- resurrection (docker)
- support (docker)

Различаться MAIN и TEST должны только:
- env-файлами
- токенами
- chat/channel ids
- db/redis namespace
- compose project name

---

## Что важно НЕ делать

- не возвращаться к supervisor как к future standard
- не строить дальнейшую серверную миграцию вокруг supervisor
- не плодить параллельные runtime-модели без жёсткой фиксации канона
- не поднимать Docker contour без фиксированного compose project name

---

## Практический статус на текущий момент

### TEST
Считать:
- стабилизированным
- канонизированным
- пригодным как базовый шаблон runtime-контуров проекта

### MAIN
Считать:
- инфраструктурно существующим
- operational-моделью исторически неоднородным
- кандидатом на перевод в dockerized runtime contour
- не канонизированным до завершения следующего этапа миграции