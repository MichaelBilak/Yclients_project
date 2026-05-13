"""Aggregated metrics for the product dashboard (JSON for SPA / Chart.js)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import and_, case, func, select
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from models import Appointment, Company, PortalBranch, Transaction


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def previous_period(self) -> DateRange:
        span = self.days
        prev_end = self.start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span - 1)
        return DateRange(start=prev_start, end=prev_end)


def _pct_change(current: float, previous: float) -> Optional[float]:
    if previous == 0:
        return None if current == 0 else 100.0
    return round(100.0 * (current - previous) / previous, 2)


def _appt_revenue_filters(start: date, end: date, company_id: Optional[int]):
    parts = [
        Appointment.attendance > 0,
        Appointment.date >= start,
        Appointment.date <= end,
    ]
    if company_id is not None:
        parts.append(Appointment.company_id == company_id)
    return and_(*parts)


def _appt_all_filters(start: date, end: date, company_id: Optional[int]):
    parts = [
        Appointment.date >= start,
        Appointment.date <= end,
    ]
    if company_id is not None:
        parts.append(Appointment.company_id == company_id)
    return and_(*parts)


async def _revenue_block(
    db: AsyncSession,
    dr: DateRange,
    company_id: Optional[int],
) -> dict[str, Any]:
    cond = _appt_revenue_filters(dr.start, dr.end, company_id)
    rev = func.coalesce(func.sum(Transaction.cost * Transaction.amount), 0.0)
    stmt = (
        select(
            rev.label('revenue'),
            func.count(func.distinct(Appointment.id)).label('appointments'),
            func.count(func.distinct(Appointment.client_id)).label('unique_clients'),
        )
        .select_from(Appointment)
        .outerjoin(Transaction, Transaction.appointment_id == Appointment.id)
        .where(cond)
    )
    row = (await db.execute(stmt)).one()
    return {
        'revenue': float(row.revenue or 0),
        'appointments': int(row.appointments or 0),
        'unique_clients': int(row.unique_clients or 0),
    }


async def fetch_summary(
    db: AsyncSession,
    start: date,
    end: date,
    company_id: Optional[int] = None,
) -> dict[str, Any]:
    current_dr = DateRange(start=start, end=end)
    prev_dr = current_dr.previous_period()

    cur = await _revenue_block(db, current_dr, company_id)
    prev = await _revenue_block(db, prev_dr, company_id)

    cur_rev = cur['revenue']
    prev_rev = prev['revenue']

    attended = func.sum(case((Appointment.attendance > 0, 1), else_=0))
    cancelled = func.sum(case((Appointment.attendance == -1, 1), else_=0))
    pending = func.sum(case((Appointment.attendance == 0, 1), else_=0))

    att_stmt = (
        select(attended, cancelled, pending)
        .select_from(Appointment)
        .where(_appt_all_filters(start, end, company_id))
    )
    att_row = (await db.execute(att_stmt)).one()

    return {
        'period': {'start': start.isoformat(), 'end': end.isoformat()},
        'previous_period': {'start': prev_dr.start.isoformat(), 'end': prev_dr.end.isoformat()},
        'revenue': {
            'total': cur_rev,
            'change_pct': _pct_change(cur_rev, prev_rev),
            'appointments': cur['appointments'],
            'appointments_change_pct': _pct_change(
                float(cur['appointments']), float(prev['appointments'])
            ),
            'unique_clients': cur['unique_clients'],
            'unique_clients_change_pct': _pct_change(
                float(cur['unique_clients']), float(prev['unique_clients'])
            ),
        },
        'appointments_breakdown': {
            'attended': int(att_row[0] or 0),
            'cancelled': int(att_row[1] or 0),
            'pending': int(att_row[2] or 0),
        },
    }


async def fetch_revenue_daily(
    db: AsyncSession,
    start: date,
    end: date,
    company_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    rev = func.coalesce(func.sum(Transaction.cost * Transaction.amount), 0.0)
    stmt = (
        select(
            Appointment.date.label('d'),
            rev.label('revenue'),
            func.count(func.distinct(Appointment.id)).label('appointments'),
        )
        .select_from(Appointment)
        .outerjoin(Transaction, Transaction.appointment_id == Appointment.id)
        .where(
            _appt_revenue_filters(start, end, company_id),
        )
        .group_by(Appointment.date)
        .order_by(Appointment.date.asc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            'date': r.d.isoformat(),
            'revenue': float(r.revenue or 0),
            'appointments': int(r.appointments or 0),
        }
        for r in rows
    ]


async def fetch_top_services(
    db: AsyncSession,
    start: date,
    end: date,
    company_id: Optional[int] = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    rev = func.coalesce(func.sum(Transaction.cost * Transaction.amount), 0.0)
    stmt = (
        select(
            Transaction.service_id,
            Transaction.service_title,
            func.sum(Transaction.amount).label('sold'),
            rev.label('revenue'),
        )
        .select_from(Transaction)
        .join(Appointment, Appointment.id == Transaction.appointment_id)
        .where(
            _appt_revenue_filters(start, end, company_id),
        )
        .group_by(Transaction.service_id, Transaction.service_title)
        .order_by(rev.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    out = []
    for r in rows:
        out.append({
            'service_id': r.service_id,
            'title': r.service_title or '',
            'sold': int(r.sold or 0),
            'revenue': float(r.revenue or 0),
        })
    return out


async def branch_company_ids(db: AsyncSession) -> Optional[list[int]]:
    """If portal_branches has rows, return allowed company ids; else None (all companies)."""
    try:
        cnt = await db.scalar(select(func.count()).select_from(PortalBranch))
    except (OperationalError, ProgrammingError, DBAPIError):
        return None
    if not cnt:
        return None
    r = await db.execute(select(PortalBranch.company_id).order_by(PortalBranch.id.asc()))
    return [row[0] for row in r.all()]


async def fetch_branches(db: AsyncSession) -> list[dict[str, Any]]:
    allowed = await branch_company_ids(db)
    stmt = select(Company).order_by(Company.id.asc())
    if allowed is not None:
        stmt = stmt.where(Company.id.in_(allowed))
    rows = (await db.execute(stmt)).scalars().all()
    return [{'id': c.id, 'title': c.title, 'group_id': c.group_id} for c in rows]
