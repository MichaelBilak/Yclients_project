"""HTTP routes for product dashboard JSON (Chart.js / SPA)."""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from auth_deps import get_dashboard_access
from auth_scope import AccessContext, query_scope
from config import SYNC_API_TOKEN
from dashboard_service import (
    fetch_branches,
    fetch_extra_services,
    fetch_plan_fact,
    fetch_revenue_daily,
    fetch_staff,
    fetch_staff_directory,
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


def _require_sync_access(ctx: AccessContext) -> None:
    if ctx.user_id is not None and ctx.role != 'super_admin':
        raise HTTPException(status_code=403, detail='Sync operations require super_admin role')


@router.get('/branches')
async def dashboard_branches(
    db: AsyncSession = Depends(get_async_db),
    ctx: AccessContext = Depends(get_dashboard_access),
):
    if ctx.full_access:
        branch_ids, force_allowed = None, False
    else:
        branch_ids, force_allowed = ctx.company_ids or [], True
    return {
        'success': True,
        'data': await fetch_branches(db, branch_ids, force_allowed=force_allowed),
    }


@router.get('/staff')
async def dashboard_staff(
    company_id: int | None = Query(None, description='Optional YClients company (salon) id'),
    db: AsyncSession = Depends(get_async_db),
    ctx: AccessContext = Depends(get_dashboard_access),
):
    scope = query_scope(ctx, company_id)
    return {
        'success': True,
        'data': await fetch_staff(
            db,
            scope['company_id'],
            allowed_company_ids=scope['branch_ids'],
            force_allowed=scope['force_allowed'],
        ),
    }


@router.get('/staff_directory.csv')
async def dashboard_staff_directory_csv(
    include_fired: bool = Query(False, description='Include fired/stale staff when true'),
    db: AsyncSession = Depends(get_async_db),
    ctx: AccessContext = Depends(get_dashboard_access),
):
    if ctx.user_id is not None and ctx.role not in {'super_admin', 'branch_admin'}:
        raise HTTPException(status_code=403, detail='Staff directory export requires admin role')

    branch_ids, force_allowed = (None, False) if ctx.full_access else (ctx.company_ids or [], True)
    rows = await fetch_staff_directory(
        db,
        include_fired,
        allowed_company_ids=branch_ids,
        force_allowed=force_allowed,
    )
    columns = [
        'company_id',
        'company_title',
        'staff_id',
        'staff_name',
        'position',
        'user_id',
        'fired',
        'working',
        'bookable',
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        buffer.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'inline; filename=staff_directory.csv'},
    )


@router.get('/widget/sync_status')
async def dashboard_widget_sync_status(
    db: AsyncSession = Depends(get_async_db),
    ctx: AccessContext = Depends(get_dashboard_access),
):
    sync_payload = await asyncio.to_thread(get_sync_status)
    queue = await SyncJobService().async_get_status_payload(db)
    return {'success': True, 'data': {'sync': sync_payload, 'queue': queue}}


@router.get('/widget/summary')
async def dashboard_widget_summary(
    start_date: date = Query(..., description='Inclusive period start'),
    end_date: date = Query(..., description='Inclusive period end'),
    company_id: int | None = Query(None, description='Optional YClients company (salon) id'),
    staff_id: int | None = Query(None, description='Optional active staff id'),
    db: AsyncSession = Depends(get_async_db),
    ctx: AccessContext = Depends(get_dashboard_access),
):
    start, end = _parse_range(start_date, end_date)
    scope = query_scope(ctx, company_id)
    return {
        'success': True,
        'data': await fetch_summary(
            db,
            start,
            end,
            scope['company_id'],
            staff_id,
            allowed_company_ids=scope['allowed_company_ids'],
        ),
    }


@router.get('/widget/revenue_daily')
async def dashboard_widget_revenue_daily(
    start_date: date = Query(...),
    end_date: date = Query(...),
    company_id: int | None = Query(None),
    staff_id: int | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
    ctx: AccessContext = Depends(get_dashboard_access),
):
    start, end = _parse_range(start_date, end_date)
    scope = query_scope(ctx, company_id)
    return {
        'success': True,
        'data': await fetch_revenue_daily(
            db,
            start,
            end,
            scope['company_id'],
            staff_id,
            allowed_company_ids=scope['allowed_company_ids'],
        ),
    }


@router.get('/widget/top_services')
async def dashboard_widget_top_services(
    start_date: date = Query(...),
    end_date: date = Query(...),
    company_id: int | None = Query(None),
    staff_id: int | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_async_db),
    ctx: AccessContext = Depends(get_dashboard_access),
):
    start, end = _parse_range(start_date, end_date)
    scope = query_scope(ctx, company_id)
    return {
        'success': True,
        'data': await fetch_top_services(
            db,
            start,
            end,
            scope['company_id'],
            limit,
            staff_id,
            allowed_company_ids=scope['allowed_company_ids'],
        ),
    }


@router.get('/widget/extra_services')
async def dashboard_widget_extra_services(
    start_date: date = Query(...),
    end_date: date = Query(...),
    company_id: int | None = Query(None),
    staff_id: int | None = Query(None),
    limit: int | None = Query(None, ge=1, le=1000),
    db: AsyncSession = Depends(get_async_db),
    ctx: AccessContext = Depends(get_dashboard_access),
):
    start, end = _parse_range(start_date, end_date)
    scope = query_scope(ctx, company_id)
    return {
        'success': True,
        'data': await fetch_extra_services(
            db,
            start,
            end,
            scope['company_id'],
            limit,
            staff_id,
            allowed_company_ids=scope['allowed_company_ids'],
        ),
    }


@router.get('/widget/plan_fact')
async def dashboard_widget_plan_fact(
    start_date: date = Query(...),
    end_date: date = Query(...),
    company_id: int | None = Query(None),
    staff_id: int | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
    ctx: AccessContext = Depends(get_dashboard_access),
):
    start, end = _parse_range(start_date, end_date)
    scope = query_scope(ctx, company_id)
    branch_ids, force_allowed = (None, False) if ctx.full_access else (ctx.company_ids or [], True)
    return {
        'success': True,
        'data': await fetch_plan_fact(
            db,
            start,
            end,
            scope['company_id'],
            staff_id,
            allowed_company_ids=branch_ids,
            force_allowed=force_allowed,
        ),
    }


@router.post('/plan/sync')
async def dashboard_plan_sync(
    x_sync_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_async_db),
    ctx: AccessContext = Depends(get_dashboard_access),
):
    _require_sync_token(x_sync_token)
    _require_sync_access(ctx)
    return {'success': True, 'data': await import_plan_sheet_from_config(db)}


@router.get('/bundle')
async def dashboard_bundle(
    start_date: date = Query(...),
    end_date: date = Query(...),
    company_id: int | None = Query(None),
    staff_id: int | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
    ctx: AccessContext = Depends(get_dashboard_access),
):
    start, end = _parse_range(start_date, end_date)
    scope = query_scope(ctx, company_id)
    summary = await fetch_summary(
        db,
        start,
        end,
        scope['company_id'],
        staff_id,
        allowed_company_ids=scope['allowed_company_ids'],
    )
    daily = await fetch_revenue_daily(
        db,
        start,
        end,
        scope['company_id'],
        staff_id,
        allowed_company_ids=scope['allowed_company_ids'],
    )
    services = await fetch_top_services(
        db,
        start,
        end,
        scope['company_id'],
        10,
        staff_id,
        allowed_company_ids=scope['allowed_company_ids'],
    )
    extra_services = await fetch_extra_services(
        db,
        start,
        end,
        scope['company_id'],
        None,
        staff_id,
        allowed_company_ids=scope['allowed_company_ids'],
    )
    return {
        'success': True,
        'data': {
            'summary': summary,
            'revenue_daily': daily,
            'top_services': services,
            'extra_services': extra_services,
        },
    }
