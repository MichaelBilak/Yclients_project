from datetime import datetime
import traceback

from config import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    SYNC_LOG_DIR,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from database import init_database
from setup_analytics import refresh_analytics_views
from sync_control import SyncControlService
from sync_logging import build_log_path, stream_run_output
from sync_notifier import TelegramNotifier, build_sync_message
from sync_pipeline import execute_sync


def run_sync_job(mode: str, trigger_type: str, initiator: str = 'system') -> dict:
    normalized_mode = (mode or 'incremental').strip().lower()
    normalized_trigger = (trigger_type or 'manual').strip().lower()
    database = init_database(DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD)
    control_db = database.get_db()
    control = SyncControlService()
    notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

    if not control.acquire_lock(control_db):
        status = control.get_status_payload(control_db)
        control_db.close()
        return {
            'started': False,
            'status': 'already_running',
            'detail': status,
        }

    log_path = build_log_path(SYNC_LOG_DIR, normalized_mode, normalized_trigger)
    control.cleanup_stale_runs(control_db)
    run = control.create_run(control_db, normalized_mode, normalized_trigger, initiator, log_path)

    result = {
        'started': True,
        'status': 'running',
        'run_id': run.id,
        'log_path': log_path,
    }
    step_results = []
    warning_count = 0
    finished_status = 'failed'
    finished_message = 'Sync interrupted'

    try:
        with stream_run_output(log_path):
            started_at = datetime.now().isoformat()
            print(f'▶ Sync run started at {started_at}')
            sync_result = execute_sync(mode=normalized_mode)
            step_results = list(sync_result.get('step_results', []))

            print('\n' + '=' * 60)
            print('  Обновление аналитических SQL views')
            print('=' * 60)
            analytics_result = refresh_analytics_views(verbose=True)
            step_results.append({
                'name': 'SQL views refresh',
                'key': 'SQL views refresh',
                'success': bool(analytics_result.get('success')),
                'elapsed': None,
            })

            warning_count = sum(1 for item in step_results if not item.get('success'))
            finished_status = 'success' if sync_result.get('success') and analytics_result.get('success') else 'failed'
            finished_message = (
                f"Sync completed with window {sync_result.get('window_start')}..{sync_result.get('window_end')}; "
                f"warnings={warning_count}; companies={sync_result.get('companies_count', 0)}"
            )
            result.update({
                'status': finished_status,
                'run_id': run.id,
                'log_path': log_path,
                'sync_result': sync_result,
            })
        control.finish_run(control_db, run, finished_status, finished_message, step_results)
    except Exception as exc:
        with stream_run_output(log_path):
            print(traceback.format_exc())
        finished_status = 'failed'
        finished_message = str(exc)
        control.finish_run(control_db, run, finished_status, finished_message, step_results)
        result.update({
            'status': finished_status,
            'error': str(exc),
            'run_id': run.id,
            'log_path': log_path,
        })
    finally:
        finished_at = datetime.now()
        message = build_sync_message(
            mode=normalized_mode,
            trigger_type=normalized_trigger,
            status=finished_status,
            started_at=run.started_at,
            finished_at=finished_at,
            log_path=log_path,
            warning_count=warning_count,
            error_message=None if finished_status == 'success' else finished_message,
        )
        notifier.send(message)
        control.release_lock(control_db)
        control_db.close()

    return result


def get_sync_status() -> dict:
    database = init_database(DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD)
    db = database.get_db()
    try:
        return SyncControlService().get_status_payload(db)
    finally:
        db.close()
