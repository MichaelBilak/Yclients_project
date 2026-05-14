"""HTTP routes for product dashboard JSON (Chart.js / SPA)."""

from __future__ import annotations

import asyncio
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from config import SYNC_API_TOKEN
from dashboard_service import (
    fetch_branches,
    fetch_plan_fact,
    fetch_revenue_daily,
    fetch_summary,
    fetch_top_services,
)
from database import get_async_db
from plan_import import import_plan_sheet_from_config
from sync_jobs import SyncJobService
from sync_orchestrator import get_sync_status

router = APIRouter()


def _parse_range(start: date, end: date) -> tuple[date, date]:
    if start > end:
        raise HTTPException(status_code=400, detail='start_date must be <= end_date')
    return start, end


def _require_sync_token(x_sync_token: str | None) -> None:
    if SYNC_API_TOKEN and x_sync_token != SYNC_API_TOKEN:
        raise HTTPException(status_code=401, detail='Invalid sync token')


@router.get('/branches')
async def dashboard_branches(db: AsyncSession = Depends(get_async_db)):
    """Companies available as salon branches (filtered when system.portal_branches is populated)."""
    return {'success': True, 'data': await fetch_branches(db)}


@router.get('/widget/sync_status')
async def dashboard_widget_sync_status(db: AsyncSession = Depends(get_async_db)):
    """Read-only sync + queue snapshot for dashboard UX (API key only, no sync token)."""
    sync_payload = await asyncio.to_thread(get_sync_status)
    queue = await SyncJobService().async_get_status_payload(db)
    return {'success': True, 'data': {'sync': sync_payload, 'queue': queue}}


@router.get('/widget/summary')
async def dashboard_widget_summary(
    start_date: date = Query(..., description='Inclusive period start'),
    end_date: date = Query(..., description='Inclusive period end'),
    company_id: int | None = Query(None, description='Optional YClients company (salon) id'),
    db: AsyncSession = Depends(get_async_db),
):
    start, end = _parse_range(start_date, end_date)
    return {'success': True, 'data': await fetch_summary(db, start, end, company_id)}


@router.get('/widget/revenue_daily')
async def dashboard_widget_revenue_daily(
    start_date: date = Query(...),
    end_date: date = Query(...),
    company_id: int | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
):
    start, end = _parse_range(start_date, end_date)
    return {'success': True, 'data': await fetch_revenue_daily(db, start, end, company_id)}


@router.get('/widget/top_services')
async def dashboard_widget_top_services(
    start_date: date = Query(...),
    end_date: date = Query(...),
    company_id: int | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_async_db),
):
    start, end = _parse_range(start_date, end_date)
    return {'success': True, 'data': await fetch_top_services(db, start, end, company_id, limit)}


@router.get('/widget/plan_fact')
async def dashboard_widget_plan_fact(
    start_date: date = Query(...),
    end_date: date = Query(...),
    company_id: int | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
):
    start, end = _parse_range(start_date, end_date)
    return {'success': True, 'data': await fetch_plan_fact(db, start, end, company_id)}


@router.post('/plan/sync')
async def dashboard_plan_sync(
    x_sync_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_async_db),
):
    _require_sync_token(x_sync_token)
    return {'success': True, 'data': await import_plan_sheet_from_config(db)}


@router.get('/bundle')
async def dashboard_bundle(
    start_date: date = Query(...),
    end_date: date = Query(...),
    company_id: int | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
):
    """Single round-trip: summary + daily revenue + top services (sequential server-side)."""
    start, end = _parse_range(start_date, end_date)
    summary = await fetch_summary(db, start, end, company_id)
    daily = await fetch_revenue_daily(db, start, end, company_id)
    services = await fetch_top_services(db, start, end, company_id, 10)
    plan_fact = await fetch_plan_fact(db, start, end, company_id)
    return {
        'success': True,
        'data': {
            'summary': summary,
            'revenue_daily': daily,
            'top_services': services,
            'plan_fact': plan_fact,
        },
    }
