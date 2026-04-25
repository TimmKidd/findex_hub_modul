# FindexHub — Project Canon

## Рабочее ядро проекта
- findex_bot/
- support_bot/
- alembic/
- main.py
- Dockerfile
- docker-compose.yml
- docker-compose.dev.yml
- docker-compose.prod.yml
- requirements.txt
- supervisord.conf
- alembic.ini
- pytest.ini
- tests/

## Канонические домены

### Объявления / публикация / модерация
- findex_bot/handlers/forms.py
- findex_bot/handlers/employer.py
- findex_bot/handlers/seeker.py
- findex_bot/handlers/moderation.py
- findex_bot/utils/ui_utils.py
- findex_bot/utils/vacancy_utils.py

### Отклики
- findex_bot/handlers/responds.py
- findex_bot/db/models.py
- findex_bot/db/repo.py

### Alerts
- findex_bot/handlers/alerts.py
- findex_bot/utils/alerts.py
- findex_bot/states/alerts.py

### Подписка
- findex_bot/handlers/subscription.py
- findex_bot/middlewares/subscription.py
- findex_bot/utils/subscription.py

### Меню / старт / help
- findex_bot/handlers/menu.py
- findex_bot/handlers/start.py
- findex_bot/handlers/help.py

### Защитные слои
- findex_bot/middlewares/published_guard.py
- findex_bot/middlewares/throttle.py
- findex_bot/handlers/fsm_watchdog.py
- findex_bot/middlewares/fsm_watchdog.py

## Inactive legacy files
- _archive/legacy_code/findex_bot/services/alerts_service.py
- _archive/legacy_code/findex_bot/workers/deliveries_retry_worker.py

Эти файлы не участвуют в каноническом runtime-контуре проекта.  
Не использовать их для правок alerts/delivery без отдельного плана.

## Архивное
- _archive/legacy_code/
- _archive/old_migrations/
- _archive/runtime_backups/
- _archive/old_logs/
- _archive/old_assets/
- _archive/runtime_artifacts/

## Что нельзя трогать без отдельного плана
- логика публикации
- модерация
- thread-логика откликов
- карточки откликов
- alert trigger logic
- callback contracts
- FSM сценарии