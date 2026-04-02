import argparse
import time

from config import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    SYNC_WORKER_POLL_INTERVAL,
)
from database import init_database
from sync_jobs import SyncJobService
from sync_orchestrator import run_sync_job


def parse_args():
    parser = argparse.ArgumentParser(description='YClients BI sync worker')
    parser.add_argument('--once', action='store_true', help='Обработать максимум одну задачу и завершиться')
    return parser.parse_args()


def process_next_job() -> bool:
    database = init_database(DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD)
    db = database.get_db()
    jobs = SyncJobService()
    try:
        job = jobs.claim_next_job(db)
        if job is None:
            return False

        result = run_sync_job(
            mode=job.mode,
            trigger_type='queued',
            initiator=job.initiator or 'worker',
        )
        if result.get('status') == 'already_running':
            jobs.release_job_to_queue(db, job)
            return False

        jobs.finish_job(db, job, result)
        return True
    except Exception as exc:
        if 'job' in locals() and job is not None:
            jobs.finish_job(db, job, {'status': 'failed', 'error': str(exc)})
        raise
    finally:
        db.close()


def main():
    args = parse_args()
    while True:
        processed = process_next_job()
        if args.once:
            return 0 if processed else 1
        if not processed:
            time.sleep(SYNC_WORKER_POLL_INTERVAL)


if __name__ == '__main__':
    raise SystemExit(main())
