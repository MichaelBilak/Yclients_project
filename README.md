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

- **API:** `GET /dashboard/bundle?start_date=&end_date=` — сводка, выручка по дням, топ услуг; план/факт загружается отдельно через `/dashboard/widget/plan_fact`; отдельные виджеты: `/dashboard/widget/summary`, `plan_fact`, `revenue_daily`, `top_services`, `sync_status`; `GET /dashboard/branches` — список компаний (филиалов), с фильтром по `system.portal_branches` после миграции `0004`.
- **CORS для SPA:** в `.env` задайте `DASHBOARD_CORS_ORIGINS=https://your-app.vercel.app` (через запятую, если несколько origin).
- **Фронт:** каталог [`web/`](web/) — Vite + Chart.js. Локально: `cd web && npm install && npm run dev` (прокси `/dashboard` на `127.0.0.1:8000` в `vite.config.js`). Основной экран — `#overview`, отдельный экран план/факт — `#plan-fact`.
- **Vercel:** в проекте Vercel укажите **Root Directory** = `web`, переменные `VITE_API_BASE`, при необходимости `VITE_API_KEY` только для демо; на API включите `DASHBOARD_CORS_ORIGINS` под домен превью.

### План/факт из Google Sheets

План хранится в таблице `plan_metrics`, факт считается из текущих данных YClients. Таблица поддерживает планы филиалов (`staff_id` пустой) и планы сотрудников (`staff_id` заполнен, `staff_category` = `barber` или `administrator`). Импорт поддерживает опубликованный Google Sheets CSV:

```env
PLAN_SHEET_CSV_URL=https://docs.google.com/spreadsheets/d/.../export?format=csv&gid=...
# Опционально. Если пусто, импорт попробует открыть лист `services` из той же таблицы.
SERVICES_SHEET_CSV_URL=https://docs.google.com/spreadsheets/d/.../gviz/tq?tqx=out:csv&sheet=services
```

После изменения Google Sheet запустите импорт:

```bash
curl -X POST http://127.0.0.1:8000/dashboard/plan/sync \
  -H "X-Sync-Token: your_token"
```

Этот же импорт обновляет метки услуг из листа `services`. Для расчета среднего чека по доп. услугам лист должен содержать `service_id` или пару `company_id` + `service_title`, а также колонку-метку вроде `доп услуга`, `метка доп услуг`, `is_extra` или `tag`. Значения `да`, `доп`, `extra`, `1` считаются доп. услугой; `нет`, `0`, `обычная` снимают метку.

Ожидаемый формат листа — плоская таблица, где одна строка = план одного сотрудника за период. Период задается через `month` в формате `YYYY-MM` или через `period_start` / `period_end`. Филиал лучше задавать через `company_id`; также поддерживается точное имя филиала в колонке `branch`. Сотрудника можно указать через `staff_id` / `stuff_id` или точное имя в `staff_name` / `stuff_name`. Категория берется из `position` (`Барбер`, `ТОП-барбер`, `Администратор`) или из текущей `Staff.position` в базе.

Пример:

```csv
month,company_id,branch,stuff_id,stuff_name,position,Выручка,СЧ общий,Кол-во клиентов,"Воск, шт","Камуфляж, шт","Уход лицо, шт","Уход голова, шт","Космо, шт",Космо сумм.,"ОПЗ, шт"
2026-05,1,Salon,123,Иван Иванов,Барбер,70000,,70,20,5,,,,5000,10
2026-05,1,Salon,456,Анна Смирнова,Администратор,30000,,30,,,,,10,10000,12
```

Пустая ячейка KPI означает, что плана по этому KPI для сотрудника нет; при импорте старое значение этого KPI удаляется. План филиала автоматически собирается как сумма планов сотрудников, если в листе нет отдельной строки филиала. Отдельные строки филиалов все еще поддерживаются и используются для проверки сумм.

Поддерживаемые колонки плана филиала и барбера: `выручка`, `кол-во клиентов`, `воск, шт`, `камуфляж, шт`, `уход лицо, шт`, `уход голова, шт`, `космо, шт`, `космо сумм.`, `опз, шт`. Для администраторов используются: `выручка`, `кол-во клиентов`, `космо, шт`, `космо сумм.`, `опз, шт`. `СЧ общий`, `ОПЗ,%` и `% доп.услуг` рассчитываются автоматически из базовых плановых значений, если не заданы явно.

Импорт возвращает `warnings`, если сумма планов сотрудников не равна плану филиала или строка `Сеть` не равна сумме филиалов. Проценты и средние значения не суммируются напрямую: для сети и филиалов они пересчитываются от базовых показателей.

Правила факта:

- `СЧ общий` = `выручка / кол-во клиентов`
- `ОПЗ` = клиент с будущей записью, созданной в день последнего посещения или на следующий день; период считается по дате создания записи
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

Без собственного домена можно временно использовать Vercel Function proxy (`web/api/[...path].js`, а также корневой `api/[...path].js` для проектов, где Vercel Root Directory не равен `web`): frontend ходит на `https://yclients-project.vercel.app/api/...`, а функция Vercel сервер-сервером проксирует запросы на VM по IP и подставляет `X-API-Key`. Для этого в Vercel задайте:

```env
VITE_API_BASE=/api
VM_API_ORIGIN=http://185.207.65.14
VM_API_KEY=<same value as API_KEY on the VM>
```

Так `VM_API_KEY` не попадает в browser bundle. На VM должен быть открыт только nginx на `80`, который проксирует `/health` и `/dashboard/*` в локальный FastAPI `127.0.0.1:8000`.

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
