from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select, text

from models import SyncJob


def _serialize_dt(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


class SyncJobService:
    def enqueue_job(self, db, mode: str, initiator: str) -> SyncJob:
        job = SyncJob(
            mode=(mode or 'incremental').strip().lower(),
            initiator=initiator,
            status='queued',
            requested_at=datetime.now(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    def claim_next_job(self, db) -> Optional[SyncJob]:
        row = db.execute(text("""
            SELECT id
            FROM system.sync_jobs
            WHERE status = 'queued'
            ORDER BY id ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        """)).first()
        if row is None:
            db.rollback()
            return None
        job = db.get(SyncJob, row.id)
        job.status = 'running'
        job.started_at = datetime.now()
        job.finished_at = None
        job.error_message = None
        db.commit()
        db.refresh(job)
        return job

    def release_job_to_queue(self, db, job: SyncJob) -> SyncJob:
        job.status = 'queued'
        job.started_at = None
        job.finished_at = None
        job.run_id = None
        job.error_message = None
        db.commit()
        db.refresh(job)
        return job

    def finish_job(self, db, job: SyncJob, result: dict[str, Any]) -> SyncJob:
        job.run_id = result.get('run_id')
        job.finished_at = datetime.now()
        job.status = result.get('status', 'failed')
        if job.status == 'success':
            job.error_message = None
        else:
            job.error_message = result.get('error') or result.get('detail') or result.get('status')
        db.commit()
        db.refresh(job)
        return job

    def get_active_job(self, db) -> Optional[SyncJob]:
        return (
            db.query(SyncJob)
            .filter(SyncJob.status.in_(('running', 'queued')))
            .order_by(
                SyncJob.status.desc(),
                SyncJob.id.asc(),
            )
            .first()
        )

    def get_latest_job(self, db) -> Optional[SyncJob]:
        return db.query(SyncJob).order_by(SyncJob.id.desc()).first()

    def get_status_payload(self, db) -> dict[str, Any]:
        current = self.get_active_job(db)
        latest = self.get_latest_job(db)
        return {
            'queued_jobs': db.query(SyncJob).filter(SyncJob.status == 'queued').count(),
            'running_jobs': db.query(SyncJob).filter(SyncJob.status == 'running').count(),
            'current_job': self.serialize(current),
            'last_job': self.serialize(latest),
        }

    @staticmethod
    def serialize(job: Optional[SyncJob]) -> Optional[dict[str, Any]]:
        if job is None:
            return None
        return {
            'id': job.id,
            'mode': job.mode,
            'initiator': job.initiator,
            'status': job.status,
            'requested_at': _serialize_dt(job.requested_at),
            'started_at': _serialize_dt(job.started_at),
            'finished_at': _serialize_dt(job.finished_at),
            'run_id': job.run_id,
            'error_message': job.error_message,
        }

    # --- Async methods (used by FastAPI endpoints) ---

    async def async_enqueue_job(self, db, mode: str, initiator: str) -> SyncJob:
        job = SyncJob(
            mode=(mode or 'incremental').strip().lower(),
            initiator=initiator,
            status='queued',
            requested_at=datetime.now(),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job

    async def async_get_status_payload(self, db) -> dict[str, Any]:
        current_result = await db.execute(
            select(SyncJob)
            .where(SyncJob.status.in_(('running', 'queued')))
            .order_by(SyncJob.status.desc(), SyncJob.id.asc())
            .limit(1)
        )
        current = current_result.scalar_one_or_none()

        latest_result = await db.execute(
            select(SyncJob).order_by(SyncJob.id.desc()).limit(1)
        )
        latest = latest_result.scalar_one_or_none()

        queued_result = await db.execute(
            select(func.count()).where(SyncJob.status == 'queued')
        )
        running_result = await db.execute(
            select(func.count()).where(SyncJob.status == 'running')
        )

        return {
            'queued_jobs': queued_result.scalar_one(),
            'running_jobs': running_result.scalar_one(),
            'current_job': self.serialize(current),
            'last_job': self.serialize(latest),
        }
