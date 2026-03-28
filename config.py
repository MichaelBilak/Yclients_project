"""
Конфигурационный файл с настройками.
Значения берутся из переменных окружения (.env файл) с fallback-значениями.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}

# ============================================================================
# Настройки YClients API
# ============================================================================
PARTNER_TOKEN = os.getenv('PARTNER_TOKEN', '')
LOGIN = os.getenv('YCLIENTS_LOGIN', '')
PASSWORD = os.getenv('YCLIENTS_PASSWORD', '')
YCLIENTS_REQUEST_DELAY = _get_float('YCLIENTS_REQUEST_DELAY', 0.25)
YCLIENTS_TIMEOUT = _get_float('YCLIENTS_TIMEOUT', 30.0)
YCLIENTS_RETRY_TOTAL = _get_int('YCLIENTS_RETRY_TOTAL', 3)
YCLIENTS_RETRY_BACKOFF = _get_float('YCLIENTS_RETRY_BACKOFF', 1.0)

# ============================================================================
# Настройки PostgreSQL
# ============================================================================
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', '5432'))
DB_NAME = os.getenv('DB_NAME', 'yclients_db')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')

# ============================================================================
# Параметры синхронизации
# ============================================================================
SYNC_DAYS = _get_int('SYNC_DAYS', 365)
SCHEDULE_DAYS = _get_int('SCHEDULE_DAYS', 60)
ANALYTICS_DAYS = _get_int('ANALYTICS_DAYS', 30)
DB_BATCH_SIZE = _get_int('DB_BATCH_SIZE', 1000)
SYNC_INCREMENTAL = _get_bool('SYNC_INCREMENTAL', True)
SYNC_LOOKBACK_DAYS = _get_int('SYNC_LOOKBACK_DAYS', 2)

# ============================================================================
# Служебные параметры синхронизации
# ============================================================================
SYNC_LOG_DIR = os.getenv('SYNC_LOG_DIR', 'logs')
SYNC_FULL_REFRESH_HOUR = _get_int('SYNC_FULL_REFRESH_HOUR', 2)
SYNC_LOCK_ID = _get_int('SYNC_LOCK_ID', 826451)
SYNC_API_TOKEN = os.getenv('SYNC_API_TOKEN', '')

# ============================================================================
# API runtime
# ============================================================================
API_HOST = os.getenv('API_HOST', '0.0.0.0')
API_PORT = _get_int('API_PORT', 8000)

# ============================================================================
# Уведомления
# ============================================================================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
