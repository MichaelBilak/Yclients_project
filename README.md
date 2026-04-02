# YClients BI System

Сервис синхронизации данных YClients в PostgreSQL, публикации BI-таблиц через FastAPI и подготовки аналитических `views` для Metabase.

## Что входит в проект

- `api.py` - FastAPI API для чтения данных, постановки sync в очередь и просмотра статуса
- `sync_pipeline.py` - production ETL pipeline YClients -> PostgreSQL
- `sync_worker.py` - worker, который обрабатывает queued sync jobs
- `main.py` - ручной CLI-запуск синхронизации
- `migrate.py` - применение Alembic миграций
- `setup_analytics.py` - создание аналитических `views` в PostgreSQL
- `docker-compose.yml` - локальный запуск `api`, `worker`, PostgreSQL и Metabase
- `sync.sh` - ручной запуск one-shot sync через Docker Compose

## Стек

- Python
- FastAPI
- SQLAlchemy
- Alembic
- PostgreSQL
- Docker Compose
- Metabase

## Быстрый старт

### 1. Подготовить окружение

```bash
cp .env.example .env
```

Заполните минимум:

- `PARTNER_TOKEN`
- `YCLIENTS_LOGIN`
- `YCLIENTS_PASSWORD`
- `DB_PASSWORD`
- `SYNC_API_TOKEN`

### 2. Применить миграции

```bash
docker compose run --rm migrate
```

### 3. Поднять сервисы

```bash
docker compose up -d postgres api worker metabase
```

После запуска будут доступны:

- API: `http://127.0.0.1:8000`
- Metabase: `http://127.0.0.1:3000`

### 4. Поставить sync в очередь

```bash
curl -X POST http://127.0.0.1:8000/sync/trigger \
  -H "Content-Type: application/json" \
  -H "X-Sync-Token: your_token" \
  -d '{"mode":"full","initiator":"bootstrap"}'
```

### 5. Проверить статус

```bash
curl http://127.0.0.1:8000/sync/status \
  -H "X-Sync-Token: your_token"
```

### 6. Пересоздать аналитические представления

```bash
docker compose run --rm analytics
```

## Полезные команды

Проверка контейнеров:

```bash
docker compose ps
```

Ручной one-shot sync:

```bash
./sync.sh incremental manual cli
```

Логи worker:

```bash
docker compose logs -f worker
```

Smoke check API:

```bash
curl http://127.0.0.1:8000/health
```

## Изменения API

- `POST /sync/trigger` теперь ставит задачу в очередь и возвращает `queued`
- `GET /sync/status` показывает и статус фактического sync run, и состояние очереди
- все list endpoints поддерживают `limit` и `offset`
- `/goods_transactions` больше не принимает `date_from/date_to`
- `/export/csv/{table}` стримит CSV без загрузки всей таблицы в память

## Тесты

Локальные unit/API тесты:

```bash
pytest tests/test_sync_parsing.py tests/test_api.py
```

Postgres integration tests:

```bash
TEST_DATABASE_URL=postgresql+psycopg2://postgres:changeme@127.0.0.1:5432/yclients_test \
pytest tests/test_postgres_integration.py
```

## Примечания

- предметные BI-таблицы пересобираются миграциями и последующим full sync
- `system.*` таблицы состояния и истории запусков сохраняются отдельно
- datasource в Metabase не provision-ится автоматически; PostgreSQL с views готов для ручного подключения через UI
