# YClients BI System

Сервис синхронизации данных YClients в PostgreSQL, публикации BI-таблиц через FastAPI и подготовки аналитических `views` для Metabase.

## Что входит в проект

- `api.py` - FastAPI API для чтения данных, постановки sync в очередь и просмотра статуса
- `sync_pipeline.py` - production ETL pipeline YClients -> PostgreSQL
- `sync_worker.py` - worker, который обрабатывает queued sync jobs
- `main.py` - ручной CLI-запуск синхронизации
- `migrate.py` - применение Alembic миграций
- `setup_analytics.py` - создание аналитических `views` в PostgreSQL
- `dashboard_service.py` / `dashboard_routes.py` — агрегаты для продуктового дашборда (JSON, без Metabase)
- `docker-compose.yml` - локальный запуск `api`, `worker`, PostgreSQL и Metabase
- `sync.sh` - ручной запуск one-shot sync через Docker Compose

## Стек

- Python
- FastAPI
- SQLAlchemy
- Alembic
- PostgreSQL
- Docker Compose
- Metabase (опционально, для внутренней BI; клиентский дашборд — через `web/` + `/dashboard/*`)

## Продуктовый дашборд (JSON + превью на Vercel)

- **API:** `GET /dashboard/bundle?start_date=&end_date=` — сводка, план/факт, выручка по дням, топ услуг; отдельные виджеты: `/dashboard/widget/summary`, `plan_fact`, `revenue_daily`, `top_services`, `sync_status`; `GET /dashboard/branches` — список компаний (филиалов), с фильтром по `system.portal_branches` после миграции `0004`.
- **CORS для SPA:** в `.env` задайте `DASHBOARD_CORS_ORIGINS=https://your-app.vercel.app` (через запятую, если несколько origin).
- **Фронт:** каталог [`web/`](web/) — Vite + Chart.js. Локально: `cd web && npm install && npm run dev` (прокси `/dashboard` на `127.0.0.1:8000` в `vite.config.js`).
- **Vercel:** в проекте Vercel укажите **Root Directory** = `web`, переменные `VITE_API_BASE`, при необходимости `VITE_API_KEY` только для демо; на API включите `DASHBOARD_CORS_ORIGINS` под домен превью.

### План/факт из Google Sheets

План хранится в таблице `plan_metrics`, факт считается из текущих данных YClients. Для MVP поддержан импорт из опубликованного Google Sheets CSV:

```env
PLAN_SHEET_CSV_URL=https://docs.google.com/spreadsheets/d/.../export?format=csv&gid=...
```

После изменения Google Sheet запустите импорт:

```bash
curl -X POST http://127.0.0.1:8000/dashboard/plan/sync \
  -H "X-Sync-Token: your_token"
```

Ожидаемый формат листа — одна строка на филиал и период. Период можно задать через `month` в формате `YYYY-MM` или через `period_start` / `period_end`. Филиал лучше задавать через `company_id`; также поддерживается точное имя филиала в колонке `branch`.

Поддерживаемые колонки плана: `выручка`, `кол-во клиентов`, `воск, шт`, `камуфляж, шт`, `уход лицо, шт`, `уход голова, шт`, `космо, шт`, `космо сумм.`, `отзывы, шт`, `опз, шт`. `СЧ общий`, `ОПЗ,%` и `% доп.услуг` рассчитываются автоматически из базовых плановых значений, если не заданы явно.

Правила факта:

- `СЧ общий` = `выручка / кол-во клиентов`
- `ОПЗ` = клиент с будущей записью, созданной в день посещения или на следующий день
- `% доп.услуг` = `(воск + камуфляж + уход лицо + уход голова) / кол-во клиентов`
- `Сеть` считается как сумма филиалов, проценты пересчитываются от суммарных базовых значений

Маппинг уходов по названию услуги:

- `SPA Volcano`, `Black mask` → `Уход лицо, шт`
- `Пилинг`, `Компл. мойка`, `Уход за гол.` → `Уход голова, шт`

### Vercel только для отображения

Vercel в этой архитектуре отдает только статический frontend из `web/`. Данные обновляются не на Vercel, а на backend-стороне: синхронизация YClients пишет свежие данные в PostgreSQL, FastAPI читает их из PostgreSQL, а frontend на Vercel забирает JSON из FastAPI.

Минимальная production-схема:

```text
https://app.example.com        -> Vercel frontend
https://api.example.com        -> FastAPI backend через VPS/nginx или named Cloudflare Tunnel
PostgreSQL                    -> только внутри backend-сервера/Docker-сети
sync worker/systemd timers     -> обновляют данные по расписанию
```

Для стабильной ссылки frontend должен смотреть на постоянный backend URL. В Vercel добавьте переменные:

```env
VITE_API_BASE=https://api.example.com
VITE_API_KEY=
```

`VITE_API_KEY` попадает в browser bundle, поэтому это не настоящий секрет. Для публичного или клиентского доступа лучше закрывать приложение через Cloudflare Access, отдельную авторизацию или read-only dashboard API.

На backend в `.env` должны быть заданы:

```env
API_KEY=change_me_strong_api_key
SYNC_API_TOKEN=change_me_sync_api_token
DASHBOARD_CORS_ORIGINS=https://your-app.vercel.app,https://app.example.com
```

Если `API_KEY` или `SYNC_API_TOKEN` пустые, соответствующая проверка в API отключается. Перед публикацией backend URL наружу эти значения нужно задать.

Автообновление данных зависит от расписания backend-синхронизации:

- `deploy/systemd/yclients-sync-incremental@.timer` запускает incremental sync каждые 4 часа.
- `deploy/systemd/yclients-sync-full@.timer` запускает full sync каждый день в 02:00.
- Если timers/worker не запущены, Vercel продолжит отображать последнюю версию данных из базы, но новые данные сами не появятся.

## Metabase

Сервис в `docker-compose` остаётся **удобным BI для команды** (ad-hoc SQL к тем же views). Для продуктового кабинета он не обязателен: см. `nginx/README.md` и пример разнесения `nginx.portal.sample.conf`. На production без Metabase можно удалить сервис `metabase` из compose и зависимость `nginx` от него, оставив только API и статику портала.

## Production (VPS)

1. VPS с Docker; `docker compose up -d postgres api worker` (+ `nginx` с профилем `prod`, SSL).
2. DNS **A** на IP; Let's Encrypt (см. `nginx/nginx.conf`).
3. Секреты только в `.env` на сервере; PostgreSQL не публиковать в интернет.
4. Подробнее по разнесению доменов: [`nginx/README.md`](nginx/README.md).

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
pytest tests/test_sync_parsing.py tests/test_api.py tests/test_dashboard_api.py
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
- миграция `0004_portal_branches` добавляет `system.portal_accounts` / `portal_branches` для будущего мультифилиального портала (пока список филиалов = все `companies`, пока нет строк в `portal_branches`)
