# YClients BI System

Система бизнес-аналитики для YClients: синхронизация данных через API, хранение в PostgreSQL, визуализация в Metabase.

## Архитектура

```
YClients API  -->  app image (api / sync / analytics)  -->  PostgreSQL  -->  Metabase
                                       |                         |
                                       |                         └─ public.* + system.sync_*
                                       ├─ main.py                └─ dashboards
                                       ├─ sync_orchestrator.py
                                       ├─ setup_analytics.py
                                       └─ api.py
```

## Структура файлов

| Файл | Назначение |
|---|---|
| `.env` | Переменные окружения (токены, пароли) |
| `.env.example` | Шаблон переменных окружения |
| `Dockerfile` | Единый образ приложения для API, sync и analytics |
| `.dockerignore` | Исключения для сборки образа |
| `docker/entrypoint.sh` | Контейнерный entrypoint: `api`, `sync`, `setup-analytics` |
| `config.py` | Конфигурация (читает из .env) |
| `yclients_api.py` | Клиент для YClients API |
| `models.py` | ORM-модели (30+ таблиц) |
| `database.py` | Подключение к PostgreSQL |
| `main.py` | Единая точка входа для sync-режимов |
| `sync_orchestrator.py` | Оркестрация запусков, lock, status, notifier |
| `sync_control.py` | Управление `system.sync_*` таблицами |
| `sync_logging.py` | Построчное логирование запуска |
| `sync_notifier.py` | Telegram-уведомления |
| `test.py` | Реализация sync-шагов и загрузчиков сущностей |
| `api.py` | FastAPI REST-сервер + /sync/trigger |
| `setup_analytics.py` | Создание аналитических views |
| `sync.sh` | Docker wrapper для ручного sync-запуска |
| `docker-compose.yml` | Единый compose: app + PostgreSQL + Metabase + `prod`-профиль для Nginx/Certbot |
| `deploy/systemd/` | Шаблоны для внешнего автозапуска docker-команд на VM |
| `nginx/nginx.conf` | Reverse proxy для Metabase и FastAPI в публичном режиме |
| `docker/postgres/init/01_create_metabase_db.sql` | Инициализация служебной БД Metabase |

## Docker-First Quick Start

### 1. Подготовка окружения

```bash
cp .env.example .env
```

Заполните `.env` данными аккаунта YClients и параметрами PostgreSQL.
Синхронизация автоматически загружает данные по всем филиалам, доступным пользователю API, через таблицу `companies`.

### 2. Сборка и запуск стека

```bash
docker compose up -d --build
```

По умолчанию запускаются:
- `postgres`
- `api`
- `metabase`

Доступ:
- Metabase: `http://localhost:3000`
- FastAPI: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`

Порты PostgreSQL, FastAPI и Metabase привязаны к `127.0.0.1`.

### 3. Первый bootstrap sync

```bash
./sync.sh incremental manual bootstrap
```

То же самое без wrapper-скрипта:

```bash
docker compose run --rm sync --mode incremental --trigger manual --initiator bootstrap
```

Режимы синхронизации:
- `incremental` -- регулярная догрузка по скользящему окну
- `full` -- полный пересчёт окна `SYNC_DAYS`

### 4. Создание аналитических views

```bash
docker compose run --rm analytics
```

### 5. Полезные команды

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f postgres
docker compose run --rm sync --mode full --trigger manual --initiator cli
docker compose down
```

Логи sync-run сохраняются в `./logs`.

### 6. Эндпоинты синхронизации

- `POST /sync/trigger` -- запустить синхронизацию в фоне (`mode=incremental|full`)
- `GET /sync/status` -- проверить статус синхронизации
- `GET /health` -- healthcheck

### 7. Подключение источника данных в Metabase

При первом запуске Metabase:
- Создайте пользователя администратора
- Добавьте Data Source:
  - **Тип**: PostgreSQL
  - **Хост**: `postgres` (если Metabase и PostgreSQL в одном compose) 
  - **Порт**: `5432`
  - **База данных**: `yclients_db`
  - **Пользователь**: `postgres`
  - **Пароль**: из `.env` (`DB_PASSWORD`)

## Развёртывание на виртуальной машине

### 1. Подготовка VM (Ubuntu 22.04+)

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
```

Перелогиньтесь в сессию после добавления в группу `docker`.

### 2. Копирование проекта

```bash
scp -r . user@vm:/opt/yclients_bi_system/
ssh user@vm
cd /opt/yclients_bi_system
```

### 3. Настройка окружения

```bash
cp .env.example .env
```

Заполните `.env` и задайте безопасные:
- `DB_PASSWORD`
- `SYNC_API_TOKEN`
- `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` при использовании уведомлений

### 4. Сборка и запуск

```bash
docker compose up -d --build
```

Если нужен публичный доступ через домен и SSL, используйте тот же compose с профилем:

```bash
docker compose --profile prod up -d --build
```

### 5. Первый прогон sync и analytics

```bash
./sync.sh incremental manual bootstrap
docker compose run --rm analytics
```

### 6. Проверка

```bash
docker compose ps
curl http://127.0.0.1:8000/health
```

### 7. Защита ручного trigger API

Если задан `SYNC_API_TOKEN`, то ручки:
- `POST /sync/trigger`
- `GET /sync/status`

требуют заголовок:

```bash
X-Sync-Token: <ваш токен>
```

Пример ручного запуска:

```bash
curl -X POST https://bi.your-domain.com/yclients-api/sync/trigger \
  -H "Content-Type: application/json" \
  -H "X-Sync-Token: your_token" \
  -d '{"mode":"incremental","initiator":"dashboard"}'
```

Не оставляйте `SYNC_API_TOKEN` пустым, если API доступен вне localhost.

## Дашборды в Metabase

Рекомендуемая структура:

| Дашборд | Источники данных |
|---|---|
| Общий обзор | `v_revenue_daily`, `v_attendance_stats`, `v_revenue_monthly` |
| Финансы | `v_finance_daily`, `v_finance_by_account`, `v_finance_monthly` |
| Сотрудники | `v_revenue_by_staff`, `v_staff_workload`, `v_staff_reviews` |
| Клиенты | `v_client_analytics`, `v_attendance_stats`, `v_reviews_monthly` |
| Товары | `v_goods_sales`, `v_goods_movement` |

Создавать дашборды можно вручную в UI Metabase (самый быстрый и практичный путь). Автоматизация через API Metabase возможна, но обычно сложнее в поддержке.

## Автообновление

Чтобы дашборды обновлялись автоматически, нужно настроить 2 уровня:

1. Автосинхронизация данных в PostgreSQL:
На этом этапе docker-команды уже унифицированы:

```bash
docker compose run --rm sync --mode incremental --trigger scheduled --initiator scheduler
docker compose run --rm sync --mode full --trigger scheduled --initiator scheduler
```

На эти команды удобно навешивать внешний scheduler на VM. Конкретный способ автозапуска можно выбрать отдельно.

Логи синхронизации:
- `logs/sync_*.log` -- детальный лог конкретного sync-run

Служебные таблицы синхронизации находятся в отдельной schema:
- `system.sync_state`
- `system.sync_runs`
- `system.sync_step_runs`

В production-режиме профиль `prod` в `docker-compose.yml` проксирует FastAPI через `https://<домен>/yclients-api/`.

2. Авто-refresh самого дашборда в Metabase:
- Откройте дашборд
- Нажмите `Refresh` (иконка обновления)
- Выберите интервал `Auto refresh` (например, 5 или 10 минут)

Для публичной ссылки можно добавить в URL фрагмент `#refresh=60` (обновление раз в 60 секунд).

## Управление пользователями

В Metabase: Admin -> People

- **Admin** -- полный доступ ко всем настройкам и дашбордам
- **User** -- просмотр дашбордов
- Разграничение доступа: Admin -> Permissions (по группам и коллекциям)
