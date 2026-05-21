"""Aggregated metrics for the product dashboard (JSON for SPA / Chart.js)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

from sqlalchemy import String, and_, case, cast, func, or_, select
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Appointment,
    Company,
    GoodTransaction,
    PlanMetric,
    PortalBranch,
    Service,
    ServiceLabel,
    Staff,
    Transaction,
)
from plan_config import (
    PLAN_FACT_METRICS,
    RAW_PLAN_FACT_CODES,
    STAFF_CATEGORY_LABELS,
    STAFF_CATEGORY_METRIC_CODES,
    metrics_for_category,
    normalize_staff_category,
)

GOODS_SALE_TYPE_ID = 1
WAITLIST_STAFF_NAME = 'лист ожидания'
ADMIN_PLACEHOLDER_STAFF_PREFIX = 'администратор'

WAX_TITLE_PARTS = ('воск',)
CAMOUFLAGE_TITLE_PARTS = ('камуфляж',)
FACE_CARE_TITLE_PARTS = ('spa volcano', 'спа volcano', 'black mask')
HEAD_CARE_TITLE_PARTS = ('пилинг', 'компл. мойка', 'уход за гол')


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


def _safe_div(numerator: float, denominator: float) -> float:
    return float(numerator or 0) / float(denominator or 0) if denominator else 0.0


def _is_waitlist_staff_name(value: Any) -> bool:
    return str(value or '').strip().casefold() == WAITLIST_STAFF_NAME


def _is_admin_placeholder_staff_name(value: Any) -> bool:
    return str(value or '').strip().casefold().startswith(ADMIN_PLACEHOLDER_STAFF_PREFIX)


def _coerce_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _appt_revenue_filters(
    start: date,
    end: date,
    company_id: Optional[int],
    staff_id: Optional[int] = None,
):
    parts = [
        Appointment.attendance > 0,
        Appointment.date >= start,
        Appointment.date <= end,
    ]
    if company_id is not None:
        parts.append(Appointment.company_id == company_id)
    if staff_id is not None:
        parts.append(Appointment.staff_id == staff_id)
    return and_(*parts)


def _appt_all_filters(
    start: date,
    end: date,
    company_id: Optional[int],
    staff_id: Optional[int] = None,
):
    parts = [
        Appointment.date >= start,
        Appointment.date <= end,
    ]
    if company_id is not None:
        parts.append(Appointment.company_id == company_id)
    if staff_id is not None:
        parts.append(Appointment.staff_id == staff_id)
    return and_(*parts)


def _goods_revenue_filters(
    start: date,
    end: date,
    company_id: Optional[int],
    staff_id: Optional[int] = None,
):
    parts = [
        GoodTransaction.type_id == GOODS_SALE_TYPE_ID,
        func.date(GoodTransaction.date) >= start,
        func.date(GoodTransaction.date) <= end,
    ]
    if company_id is not None:
        parts.append(GoodTransaction.company_id == company_id)
    if staff_id is not None:
        parts.append(GoodTransaction.master_id == staff_id)
    return and_(*parts)


async def _goods_revenue_total(
    db: AsyncSession,
    dr: DateRange,
    company_id: Optional[int],
    staff_id: Optional[int] = None,
) -> float:
    stmt = (
        select(func.coalesce(func.sum(GoodTransaction.cost), 0.0).label('revenue'))
        .where(_goods_revenue_filters(dr.start, dr.end, company_id, staff_id))
    )
    row = (await db.execute(stmt)).one()
    return float(row.revenue or 0)


async def _goods_sold_count(
    db: AsyncSession,
    dr: DateRange,
    company_id: Optional[int],
    staff_id: Optional[int] = None,
) -> float:
    sold_qty = func.coalesce(
        func.sum(func.abs(func.coalesce(GoodTransaction.amount, 0.0))),
        0.0,
    )
    stmt = (
        select(sold_qty.label('qty'))
        .where(_goods_revenue_filters(dr.start, dr.end, company_id, staff_id))
    )
    row = (await db.execute(stmt)).one()
    return float(row.qty or 0)


def _title_matches(title_expr, parts: tuple[str, ...]):
    conditions = []
    for part in parts:
        conditions.append(title_expr.like(f'%{part.lower()}%'))
        conditions.append(title_expr.like(f'%{part}%'))
    return or_(*conditions)


def _service_qty_sum(title_expr, parts: tuple[str, ...]):
    return func.coalesce(
        func.sum(
            case(
                (_title_matches(title_expr, parts), func.coalesce(Transaction.amount, 0)),
                else_=0,
            )
        ),
        0,
    )


def _derive_metric_values(
    values: dict[str, float],
    *,
    include_zero_derived: bool,
    prefer_explicit: bool = True,
) -> dict[str, float]:
    out = {code: float(value) for code, value in values.items() if value is not None}

    clients = out.get('clients', 0.0)
    if (not prefer_explicit or 'avg_check_total' not in out) and (
        include_zero_derived or {'revenue', 'clients'} <= out.keys()
    ):
        out['avg_check_total'] = out.get('revenue', 0.0) / clients if clients else 0.0

    if (not prefer_explicit or 'opz_pct' not in out) and (
        include_zero_derived or {'opz_qty', 'clients'} <= out.keys()
    ):
        out['opz_pct'] = 100.0 * out.get('opz_qty', 0.0) / clients if clients else 0.0

    if (not prefer_explicit or 'extra_services_pct' not in out) and (
        include_zero_derived
        or (
            'clients' in out
            and any(
                code in out
                for code in ('wax_qty', 'camouflage_qty', 'face_care_qty', 'head_care_qty')
            )
        )
    ):
        extra_qty = (
            out.get('wax_qty', 0.0)
            + out.get('camouflage_qty', 0.0)
            + out.get('face_care_qty', 0.0)
            + out.get('head_care_qty', 0.0)
        )
        out['extra_services_pct'] = 100.0 * extra_qty / clients if clients else 0.0

    return out


def _sum_metric_components(component_rows: list[dict[str, float]]) -> dict[str, float]:
    summed: dict[str, float] = {}
    for values in component_rows:
        for code in RAW_PLAN_FACT_CODES:
            if code in values:
                summed[code] = summed.get(code, 0.0) + float(values[code] or 0.0)
    return _derive_metric_values(summed, include_zero_derived=False, prefer_explicit=False)


def _round_optional(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def _completion_status(completion_pct: Optional[float]) -> str:
    if completion_pct is None:
        return 'no-plan'
    if completion_pct >= 100:
        return 'ok'
    if completion_pct >= 80:
        return 'warn'
    return 'bad'


async def _revenue_block(
    db: AsyncSession,
    dr: DateRange,
    company_id: Optional[int],
    staff_id: Optional[int] = None,
) -> dict[str, Any]:
    cond = _appt_revenue_filters(dr.start, dr.end, company_id, staff_id)
    rev = func.coalesce(func.sum(Transaction.cost * Transaction.amount), 0.0)
    extra_rev = func.coalesce(
        func.sum(
            case(
                (ServiceLabel.is_extra.is_(True), Transaction.cost * Transaction.amount),
                else_=0.0,
            )
        ),
        0.0,
    )
    extra_appt = case(
        (ServiceLabel.is_extra.is_(True), Appointment.id),
        else_=None,
    )
    service_count = func.coalesce(func.sum(func.coalesce(Transaction.amount, 0)), 0)
    extra_service_count = func.coalesce(
        func.sum(
            case(
                (ServiceLabel.is_extra.is_(True), func.coalesce(Transaction.amount, 0)),
                else_=0,
            )
        ),
        0,
    )
    stmt = (
        select(
            rev.label('revenue'),
            extra_rev.label('extra_service_revenue'),
            service_count.label('service_count'),
            extra_service_count.label('extra_service_count'),
            func.count(func.distinct(Appointment.id)).label('appointments'),
            func.count(func.distinct(extra_appt)).label('extra_service_appointments'),
            func.count(func.distinct(Appointment.client_id)).label('unique_clients'),
        )
        .select_from(Appointment)
        .outerjoin(Transaction, Transaction.appointment_id == Appointment.id)
        .outerjoin(ServiceLabel, ServiceLabel.service_id == Transaction.service_id)
        .where(cond)
    )
    row = (await db.execute(stmt)).one()
    service_revenue = float(row.revenue or 0)
    extra_service_revenue = float(row.extra_service_revenue or 0)
    goods_revenue = await _goods_revenue_total(db, dr, company_id, staff_id)
    goods_count = await _goods_sold_count(db, dr, company_id, staff_id)
    return {
        'revenue': service_revenue + goods_revenue,
        'service_revenue': service_revenue,
        'goods_revenue': goods_revenue,
        'extra_service_revenue': extra_service_revenue,
        'service_count': float(row.service_count or 0),
        'goods_count': goods_count,
        'extra_service_count': float(row.extra_service_count or 0),
        'appointments': int(row.appointments or 0),
        'extra_service_appointments': int(row.extra_service_appointments or 0),
        'unique_clients': int(row.unique_clients or 0),
    }


async def fetch_summary(
    db: AsyncSession,
    start: date,
    end: date,
    company_id: Optional[int] = None,
    staff_id: Optional[int] = None,
) -> dict[str, Any]:
    current_dr = DateRange(start=start, end=end)
    prev_dr = current_dr.previous_period()

    cur = await _revenue_block(db, current_dr, company_id, staff_id)
    prev = await _revenue_block(db, prev_dr, company_id, staff_id)

    cur_rev = cur['revenue']
    prev_rev = prev['revenue']
    cur_appointments = float(cur['appointments'] or 0)
    prev_appointments = float(prev['appointments'] or 0)
    cur_avg_total = _safe_div(cur_rev, cur_appointments)
    prev_avg_total = _safe_div(prev_rev, prev_appointments)
    cur_avg_services = _safe_div(cur['service_revenue'], cur_appointments)
    prev_avg_services = _safe_div(prev['service_revenue'], prev_appointments)
    cur_avg_goods = _safe_div(cur['goods_revenue'], cur_appointments)
    prev_avg_goods = _safe_div(prev['goods_revenue'], prev_appointments)
    cur_avg_extra_services = _safe_div(cur['extra_service_revenue'], cur_appointments)
    prev_avg_extra_services = _safe_div(prev['extra_service_revenue'], prev_appointments)

    attended = func.sum(case((Appointment.attendance > 0, 1), else_=0))
    cancelled = func.sum(case((Appointment.attendance == -1, 1), else_=0))
    pending = func.sum(case((Appointment.attendance == 0, 1), else_=0))

    att_stmt = (
        select(attended, cancelled, pending)
        .select_from(Appointment)
        .where(_appt_all_filters(start, end, company_id, staff_id))
    )
    att_row = (await db.execute(att_stmt)).one()

    return {
        'period': {'start': start.isoformat(), 'end': end.isoformat()},
        'previous_period': {'start': prev_dr.start.isoformat(), 'end': prev_dr.end.isoformat()},
        'revenue': {
            'total': cur_rev,
            'service_revenue': cur['service_revenue'],
            'goods_revenue': cur['goods_revenue'],
            'extra_service_revenue': cur['extra_service_revenue'],
            'change_pct': _pct_change(cur_rev, prev_rev),
            'service_revenue_change_pct': _pct_change(
                float(cur['service_revenue']), float(prev['service_revenue'])
            ),
            'goods_revenue_change_pct': _pct_change(
                float(cur['goods_revenue']), float(prev['goods_revenue'])
            ),
            'extra_service_revenue_change_pct': _pct_change(
                float(cur['extra_service_revenue']), float(prev['extra_service_revenue'])
            ),
            'service_count': cur['service_count'],
            'service_count_change_pct': _pct_change(
                float(cur['service_count']), float(prev['service_count'])
            ),
            'goods_count': cur['goods_count'],
            'goods_count_change_pct': _pct_change(
                float(cur['goods_count']), float(prev['goods_count'])
            ),
            'extra_service_count': cur['extra_service_count'],
            'extra_service_count_change_pct': _pct_change(
                float(cur['extra_service_count']), float(prev['extra_service_count'])
            ),
            'appointments': cur['appointments'],
            'appointments_change_pct': _pct_change(
                float(cur['appointments']), float(prev['appointments'])
            ),
            'extra_service_appointments': cur['extra_service_appointments'],
            'unique_clients': cur['unique_clients'],
            'unique_clients_change_pct': _pct_change(
                float(cur['unique_clients']), float(prev['unique_clients'])
            ),
        },
        'average_check': {
            'total': cur_avg_total,
            'services': cur_avg_services,
            'goods': cur_avg_goods,
            'extra_services': cur_avg_extra_services,
            'total_change_pct': _pct_change(cur_avg_total, prev_avg_total),
            'services_change_pct': _pct_change(cur_avg_services, prev_avg_services),
            'goods_change_pct': _pct_change(cur_avg_goods, prev_avg_goods),
            'extra_services_change_pct': _pct_change(
                cur_avg_extra_services,
                prev_avg_extra_services,
            ),
            'appointments': cur['appointments'],
            'extra_service_appointments': cur['extra_service_appointments'],
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
    staff_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    rev = func.coalesce(func.sum(Transaction.cost * Transaction.amount), 0.0)
    svc_stmt = (
        select(
            Appointment.date.label('d'),
            rev.label('revenue'),
            func.count(func.distinct(Appointment.id)).label('appointments'),
        )
        .select_from(Appointment)
        .outerjoin(Transaction, Transaction.appointment_id == Appointment.id)
        .where(
            _appt_revenue_filters(start, end, company_id, staff_id),
        )
        .group_by(Appointment.date)
    )

    goods_day = func.date(GoodTransaction.date)
    goods_stmt = (
        select(
            goods_day.label('d'),
            func.coalesce(func.sum(GoodTransaction.cost), 0.0).label('revenue'),
        )
        .where(_goods_revenue_filters(start, end, company_id, staff_id))
        .group_by(goods_day)
    )

    svc_rows = (await db.execute(svc_stmt)).all()
    goods_rows = (await db.execute(goods_stmt)).all()

    by_date: dict[date, dict[str, float | int]] = {}
    for r in svc_rows:
        day = _coerce_date(r.d)
        by_date.setdefault(day, {'service_revenue': 0.0, 'goods_revenue': 0.0, 'appointments': 0})
        by_date[day]['service_revenue'] = float(r.revenue or 0)
        by_date[day]['appointments'] = int(r.appointments or 0)
    for r in goods_rows:
        day = _coerce_date(r.d)
        by_date.setdefault(day, {'service_revenue': 0.0, 'goods_revenue': 0.0, 'appointments': 0})
        by_date[day]['goods_revenue'] = float(r.revenue or 0)

    return [
        {
            'date': d.isoformat(),
            'revenue': float(v['service_revenue']) + float(v['goods_revenue']),
            'service_revenue': float(v['service_revenue']),
            'goods_revenue': float(v['goods_revenue']),
            'appointments': int(v['appointments']),
        }
        for d, v in sorted(by_date.items(), key=lambda kv: kv[0])
    ]


async def fetch_top_services(
    db: AsyncSession,
    start: date,
    end: date,
    company_id: Optional[int] = None,
    limit: int = 10,
    staff_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    rev = func.coalesce(func.sum(Transaction.cost * Transaction.amount), 0.0)
    title_expr = func.trim(func.coalesce(func.nullif(Transaction.service_title, ''), Service.title, ''))
    normalized_title = func.lower(func.replace(title_expr, 'ё', 'е'))
    group_key = func.coalesce(func.nullif(normalized_title, ''), cast(Transaction.service_id, String))
    stmt = (
        select(
            func.min(Transaction.service_id).label('service_id'),
            func.min(title_expr).label('service_title'),
            func.sum(Transaction.amount).label('sold'),
            rev.label('revenue'),
            func.count(func.distinct(Transaction.service_id)).label('service_count'),
            func.count(func.distinct(Appointment.company_id)).label('branch_count'),
        )
        .select_from(Transaction)
        .join(Appointment, Appointment.id == Transaction.appointment_id)
        .outerjoin(Service, Service.id == Transaction.service_id)
        .where(
            _appt_revenue_filters(start, end, company_id, staff_id),
        )
        .group_by(group_key)
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
            'service_count': int(r.service_count or 0),
            'branch_count': int(r.branch_count or 0),
        })
    return out


async def fetch_extra_services(
    db: AsyncSession,
    start: date,
    end: date,
    company_id: Optional[int] = None,
    limit: int = 50,
    staff_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    rev = func.coalesce(func.sum(Transaction.cost * Transaction.amount), 0.0)
    title_expr = func.trim(func.coalesce(func.nullif(Transaction.service_title, ''), Service.title, ''))
    normalized_title = func.lower(func.replace(title_expr, 'ё', 'е'))
    group_key = func.coalesce(func.nullif(normalized_title, ''), cast(Transaction.service_id, String))
    stmt = (
        select(
            func.min(Transaction.service_id).label('service_id'),
            func.min(title_expr).label('service_title'),
            func.coalesce(func.sum(Transaction.amount), 0).label('sold'),
            rev.label('revenue'),
            func.count(func.distinct(Transaction.service_id)).label('service_count'),
            func.count(func.distinct(Appointment.company_id)).label('branch_count'),
        )
        .select_from(Transaction)
        .join(Appointment, Appointment.id == Transaction.appointment_id)
        .join(ServiceLabel, ServiceLabel.service_id == Transaction.service_id)
        .outerjoin(Service, Service.id == Transaction.service_id)
        .where(
            _appt_revenue_filters(start, end, company_id, staff_id),
            ServiceLabel.is_extra.is_(True),
        )
        .group_by(group_key)
        .order_by(func.coalesce(func.sum(Transaction.amount), 0).desc(), rev.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            'service_id': r.service_id,
            'title': r.service_title or '',
            'sold': int(r.sold or 0),
            'revenue': float(r.revenue or 0),
            'service_count': int(r.service_count or 0),
            'branch_count': int(r.branch_count or 0),
        }
        for r in rows
    ]


async def _service_group_counts(
    db: AsyncSession,
    start: date,
    end: date,
    company_id: int,
    staff_id: Optional[int] = None,
) -> dict[str, float]:
    title_expr = func.lower(func.coalesce(Transaction.service_title, Service.title, ''))
    stmt = (
        select(
            _service_qty_sum(title_expr, WAX_TITLE_PARTS).label('wax_qty'),
            _service_qty_sum(title_expr, CAMOUFLAGE_TITLE_PARTS).label('camouflage_qty'),
            _service_qty_sum(title_expr, FACE_CARE_TITLE_PARTS).label('face_care_qty'),
            _service_qty_sum(title_expr, HEAD_CARE_TITLE_PARTS).label('head_care_qty'),
        )
        .select_from(Transaction)
        .join(Appointment, Appointment.id == Transaction.appointment_id)
        .outerjoin(Service, Service.id == Transaction.service_id)
        .where(_appt_revenue_filters(start, end, company_id, staff_id))
    )
    row = (await db.execute(stmt)).one()
    return {
        'wax_qty': float(row.wax_qty or 0),
        'camouflage_qty': float(row.camouflage_qty or 0),
        'face_care_qty': float(row.face_care_qty or 0),
        'head_care_qty': float(row.head_care_qty or 0),
    }


async def _goods_sales_metrics(
    db: AsyncSession,
    start: date,
    end: date,
    company_id: int,
    staff_id: Optional[int] = None,
) -> dict[str, float]:
    # YClients stores goods sales as negative stock movements.
    sold_qty = func.sum(-func.coalesce(GoodTransaction.amount, 0.0))
    stmt = (
        select(
            func.coalesce(sold_qty, 0.0).label('qty'),
            func.coalesce(func.sum(GoodTransaction.cost), 0.0).label('revenue'),
        )
        .where(_goods_revenue_filters(start, end, company_id, staff_id))
    )
    row = (await db.execute(stmt)).one()
    return {
        'cosmo_qty': float(row.qty or 0),
        'cosmo_sum': float(row.revenue or 0),
    }


async def _opz_count(
    db: AsyncSession,
    start: date,
    end: date,
    company_id: int,
    staff_id: Optional[int] = None,
    created_user_id: Optional[int] = None,
) -> float:
    create_start = datetime.combine(start, time.min)
    create_end = datetime.combine(end + timedelta(days=1), time.min)
    candidate_filters = [
        Appointment.company_id == company_id,
        Appointment.client_id.is_not(None),
        Appointment.date.is_not(None),
        Appointment.create_date.is_not(None),
        Appointment.create_date >= create_start,
        Appointment.create_date < create_end,
    ]
    if created_user_id is not None:
        candidate_filters.append(Appointment.created_user_id == created_user_id)
    candidates_stmt = (
        select(
            Appointment.id,
            Appointment.company_id,
            Appointment.client_id,
            Appointment.date,
            Appointment.create_date,
        )
        .where(*candidate_filters)
    )
    candidates = (await db.execute(candidates_stmt)).all()
    if not candidates:
        return 0.0

    client_ids = sorted({candidate.client_id for candidate in candidates if candidate.client_id is not None})
    visit_filters = [
        Appointment.company_id == company_id,
        Appointment.attendance > 0,
        Appointment.client_id.in_(client_ids),
        Appointment.date.is_not(None),
        Appointment.date <= end,
    ]
    visits_stmt = (
        select(
            Appointment.company_id,
            Appointment.client_id,
            Appointment.staff_id,
            Appointment.date,
        )
        .where(*visit_filters)
    )
    visits = (await db.execute(visits_stmt)).all()
    visits_by_client: dict[tuple[int, int], list[Any]] = {}
    for visit in visits:
        visits_by_client.setdefault((visit.company_id, visit.client_id), []).append(visit)

    booked_clients: set[tuple[int, int]] = set()
    for candidate in candidates:
        create_day = candidate.create_date.date()
        last_visit_date: date | None = None
        last_visit_matches_staff = staff_id is None
        for visit in visits_by_client.get((candidate.company_id, candidate.client_id), []):
            if visit.date > create_day:
                continue
            if last_visit_date is None or visit.date > last_visit_date:
                last_visit_date = visit.date
                last_visit_matches_staff = staff_id is None or visit.staff_id == staff_id
            elif staff_id is not None and visit.date == last_visit_date and visit.staff_id == staff_id:
                last_visit_matches_staff = True
        if last_visit_date is None or not last_visit_matches_staff:
            continue
        if candidate.date <= last_visit_date:
            continue
        if create_day in {last_visit_date, last_visit_date + timedelta(days=1)}:
            booked_clients.add((candidate.company_id, candidate.client_id))

    return float(len(booked_clients))


async def _fact_metric_components(
    db: AsyncSession,
    start: date,
    end: date,
    company_id: int,
    staff_id: Optional[int] = None,
    created_user_id: Optional[int] = None,
) -> dict[str, float]:
    revenue = await _revenue_block(db, DateRange(start, end), company_id, staff_id)
    opz_staff_id = None if created_user_id is not None else staff_id
    values: dict[str, float] = {
        'revenue': float(revenue['revenue'] or 0),
        'clients': float(revenue['unique_clients'] or 0),
        'opz_qty': await _opz_count(
            db, start, end, company_id,
            staff_id=opz_staff_id,
            created_user_id=created_user_id,
        ),
    }
    values.update(await _service_group_counts(db, start, end, company_id, staff_id))
    values.update(await _goods_sales_metrics(db, start, end, company_id, staff_id))
    return _derive_metric_values(values, include_zero_derived=True, prefer_explicit=False)


async def _plan_metric_components_by_company(
    db: AsyncSession,
    start: date,
    end: date,
    company_ids: list[int],
) -> dict[int, dict[str, float]]:
    if not company_ids:
        return {}
    metric_codes = {metric['code'] for metric in PLAN_FACT_METRICS}
    stmt = (
        select(PlanMetric.company_id, PlanMetric.metric_code, PlanMetric.value)
        .where(
            PlanMetric.period_start == start,
            PlanMetric.period_end == end,
            PlanMetric.company_id.in_(company_ids),
            PlanMetric.staff_id.is_(None),
            PlanMetric.metric_code.in_(metric_codes),
        )
    )
    rows = (await db.execute(stmt)).all()
    out: dict[int, dict[str, float]] = {company_id: {} for company_id in company_ids}
    for row in rows:
        out.setdefault(row.company_id, {})[row.metric_code] = float(row.value or 0)
    return {
        company_id: _derive_metric_values(values, include_zero_derived=False)
        for company_id, values in out.items()
    }


async def _plan_metric_components_by_staff(
    db: AsyncSession,
    start: date,
    end: date,
    company_id: int,
    staff_ids: list[int],
) -> tuple[dict[int, dict[str, float]], dict[int, str]]:
    if not staff_ids:
        return {}, {}
    metric_codes = {metric['code'] for metric in PLAN_FACT_METRICS}
    stmt = (
        select(PlanMetric.staff_id, PlanMetric.staff_category, PlanMetric.metric_code, PlanMetric.value)
        .where(
            PlanMetric.period_start == start,
            PlanMetric.period_end == end,
            PlanMetric.company_id == company_id,
            PlanMetric.staff_id.in_(staff_ids),
            PlanMetric.metric_code.in_(metric_codes),
        )
    )
    rows = (await db.execute(stmt)).all()
    out: dict[int, dict[str, float]] = {staff_id: {} for staff_id in staff_ids}
    categories: dict[int, str] = {}
    for row in rows:
        if row.staff_id is None:
            continue
        staff_id = int(row.staff_id)
        out.setdefault(staff_id, {})[row.metric_code] = float(row.value or 0)
        if row.staff_category in STAFF_CATEGORY_METRIC_CODES:
            categories[staff_id] = row.staff_category
    return {
        staff_id: _derive_metric_values(values, include_zero_derived=False)
        for staff_id, values in out.items()
    }, categories


async def _resolve_plan_period(
    db: AsyncSession,
    start: date,
    end: date,
    company_ids: list[int],
) -> tuple[date, date]:
    if not company_ids:
        return start, end

    exact_count = await db.scalar(
        select(func.count())
        .select_from(PlanMetric)
        .where(
            PlanMetric.period_start == start,
            PlanMetric.period_end == end,
            PlanMetric.company_id.in_(company_ids),
        )
    )
    if exact_count:
        return start, end

    row = (
        await db.execute(
            select(PlanMetric.period_start, PlanMetric.period_end)
            .where(PlanMetric.company_id.in_(company_ids))
            .group_by(PlanMetric.period_start, PlanMetric.period_end)
            .order_by(PlanMetric.period_start.desc(), PlanMetric.period_end.desc())
            .limit(1)
        )
    ).first()
    if row:
        return row.period_start, row.period_end
    return start, end


def _metric_cells(
    plan_values: dict[str, float],
    fact_values: dict[str, float],
    metrics: tuple[dict[str, str], ...] = PLAN_FACT_METRICS,
) -> list[dict[str, Any]]:
    cells = []
    for metric in metrics:
        code = metric['code']
        plan = plan_values.get(code)
        fact = fact_values.get(code, 0.0)
        remaining = None if plan is None else plan - fact
        if plan is None:
            completion_pct = None
        elif plan == 0:
            completion_pct = 100.0 if fact >= 0 else None
        else:
            completion_pct = 100.0 * fact / plan
        cells.append({
            'code': code,
            'plan': _round_optional(plan),
            'fact': _round_optional(fact),
            'remaining': _round_optional(remaining),
            'completion_pct': _round_optional(completion_pct),
            'status': _completion_status(completion_pct),
        })
    return cells


def _metric_sets_payload() -> dict[str, list[dict[str, str]]]:
    return {
        'branch': list(PLAN_FACT_METRICS),
        **{
            category: list(metrics_for_category(category))
            for category in STAFF_CATEGORY_METRIC_CODES
        },
    }


def _staff_category(staff_row: Any, plan_category: str | None, plan_values: dict[str, float] | None = None) -> str:
    if plan_category in STAFF_CATEGORY_METRIC_CODES:
        return plan_category
    category = normalize_staff_category(getattr(staff_row, 'position', None))
    if category in STAFF_CATEGORY_METRIC_CODES:
        return category
    return 'barber' if plan_values else 'unknown'


async def _fetch_company_staff(
    db: AsyncSession,
    company_id: int,
    staff_id: Optional[int] = None,
) -> list[Any]:
    stmt = (
        select(Staff.id, Staff.name, Staff.position, Staff.user_id, Staff.fired)
        .where(Staff.company_id == company_id, Staff.fired == 0)
        .order_by(Staff.position.asc(), Staff.name.asc())
    )
    if staff_id is not None:
        stmt = stmt.where(Staff.id == staff_id)
    return [
        row for row in (await db.execute(stmt)).all()
        if (
            not _is_waitlist_staff_name(row.name)
            and not _is_admin_placeholder_staff_name(row.name)
        )
    ]


async def fetch_staff(
    db: AsyncSession,
    company_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    allowed = await branch_company_ids(db)
    stmt = (
        select(
            Staff.id,
            Staff.name,
            Staff.position,
            Staff.user_id,
            Staff.company_id,
            Company.title.label('company_title'),
        )
        .select_from(Staff)
        .join(Company, Company.id == Staff.company_id)
        .where(Staff.fired == 0)
        .order_by(Company.title.asc(), Staff.name.asc(), Staff.id.asc())
    )
    if allowed is not None:
        stmt = stmt.where(Company.id.in_(allowed))
    if company_id is not None:
        stmt = stmt.where(Company.id == company_id)

    rows = (await db.execute(stmt)).all()
    return [
        {
            'id': row.id,
            'name': row.name,
            'position': row.position,
            'user_id': row.user_id,
            'company_id': row.company_id,
            'company_title': row.company_title,
        }
        for row in rows
        if (
            not _is_waitlist_staff_name(row.name)
            and not _is_admin_placeholder_staff_name(row.name)
        )
    ]


async def fetch_plan_fact(
    db: AsyncSession,
    start: date,
    end: date,
    company_id: Optional[int] = None,
    staff_id: Optional[int] = None,
) -> dict[str, Any]:
    branches = await fetch_branches(db)
    selected_staff: dict[str, Any] | None = None
    if staff_id is not None:
        staff_rows = await fetch_staff(db)
        selected_staff = next((staff for staff in staff_rows if staff['id'] == staff_id), None)
        if selected_staff is not None:
            if company_id is None:
                company_id = int(selected_staff['company_id'])
            elif int(selected_staff['company_id']) != company_id:
                selected_staff = None
        if selected_staff is None and company_id is None:
            company_id = -1

    if company_id is not None:
        branches = [branch for branch in branches if branch['id'] == company_id]

    company_ids = [int(branch['id']) for branch in branches]
    plan_start, plan_end = await _resolve_plan_period(db, start, end, company_ids)
    plans_by_company = await _plan_metric_components_by_company(db, plan_start, plan_end, company_ids)

    if company_id is not None:
        if not company_ids:
            return {
                'period': {'start': start.isoformat(), 'end': end.isoformat()},
                'plan_period': {'start': plan_start.isoformat(), 'end': plan_end.isoformat()},
                'view_scope': 'staff',
                'selected_staff': selected_staff,
                'metrics': list(PLAN_FACT_METRICS),
                'metric_sets': _metric_sets_payload(),
                'groups': [],
            }

        branch_id = company_ids[0]
        branch = branches[0]
        staff_rows = await _fetch_company_staff(db, branch_id, staff_id)
        staff_ids = [int(row.id) for row in staff_rows]
        plans_by_staff, categories_by_staff = await _plan_metric_components_by_staff(
            db,
            plan_start,
            plan_end,
            branch_id,
            staff_ids,
        )
        categories_by_staff_id: dict[int, str] = {}
        for staff in staff_rows:
            sid = int(staff.id)
            plan_values = plans_by_staff.get(sid, {})
            categories_by_staff_id[sid] = _staff_category(staff, categories_by_staff.get(sid), plan_values)

        user_id_by_staff: dict[int, Optional[int]] = {
            int(staff.id): getattr(staff, 'user_id', None) for staff in staff_rows
        }

        facts_by_staff: dict[int, dict[str, float]] = {}
        for staff_id in staff_ids:
            admin_user_id = (
                user_id_by_staff.get(staff_id)
                if categories_by_staff_id.get(staff_id) == 'administrator'
                else None
            )
            facts_by_staff[staff_id] = await _fact_metric_components(
                db, start, end, branch_id, staff_id,
                created_user_id=admin_user_id,
            )

        branch_fact = await _fact_metric_components(db, start, end, branch_id)
        parent_group = {
            'company_id': branch_id,
            'title': branch['title'],
            'scope': 'branch',
            'metrics': _metric_cells(plans_by_company.get(branch_id, {}), branch_fact),
        }

        groups: list[dict[str, Any]] = []
        for staff in staff_rows:
            staff_id = int(staff.id)
            plan_values = plans_by_staff.get(staff_id, {})
            category = categories_by_staff_id[staff_id]
            metrics = metrics_for_category(category)
            groups.append({
                'company_id': branch_id,
                'staff_id': staff_id,
                'title': staff.name,
                'position': staff.position,
                'scope': 'staff',
                'category': category,
                'category_label': STAFF_CATEGORY_LABELS.get(category, STAFF_CATEGORY_LABELS['unknown']),
                'metrics': _metric_cells(
                    plan_values,
                    facts_by_staff.get(staff_id, {}),
                    metrics,
                ),
            })

        return {
            'period': {'start': start.isoformat(), 'end': end.isoformat()},
            'plan_period': {'start': plan_start.isoformat(), 'end': plan_end.isoformat()},
            'view_scope': 'staff',
            'branch': branch,
            'selected_staff': selected_staff,
            'parent_group': parent_group,
            'metrics': list(PLAN_FACT_METRICS),
            'metric_sets': _metric_sets_payload(),
            'groups': groups,
        }

    facts_by_company: dict[int, dict[str, float]] = {}
    for branch_id in company_ids:
        facts_by_company[branch_id] = await _fact_metric_components(db, start, end, branch_id)

    groups: list[dict[str, Any]] = []
    if company_id is None and company_ids:
        network_plan = _sum_metric_components([plans_by_company.get(branch_id, {}) for branch_id in company_ids])
        network_fact = _sum_metric_components([facts_by_company.get(branch_id, {}) for branch_id in company_ids])
        groups.append({
            'company_id': None,
            'title': 'Сеть',
            'scope': 'network',
            'metrics': _metric_cells(network_plan, network_fact),
        })

    for branch in branches:
        branch_id = int(branch['id'])
        groups.append({
            'company_id': branch_id,
            'title': branch['title'],
            'scope': 'branch',
            'metrics': _metric_cells(
                plans_by_company.get(branch_id, {}),
                facts_by_company.get(branch_id, {}),
            ),
        })

    return {
        'period': {'start': start.isoformat(), 'end': end.isoformat()},
        'plan_period': {'start': plan_start.isoformat(), 'end': plan_end.isoformat()},
        'view_scope': 'branch',
        'metrics': list(PLAN_FACT_METRICS),
        'metric_sets': _metric_sets_payload(),
        'groups': groups,
    }


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


async def fetch_staff_directory(db: AsyncSession, include_fired: bool = False) -> list[dict[str, Any]]:
    allowed = await branch_company_ids(db)
    stmt = (
        select(
            Company.id.label('company_id'),
            Company.title.label('company_title'),
            Staff.id.label('staff_id'),
            Staff.name.label('staff_name'),
            Staff.position,
            Staff.user_id,
            Staff.fired,
            Staff.bookable,
        )
        .select_from(Staff)
        .join(Company, Company.id == Staff.company_id)
        .order_by(Company.title.asc(), Staff.name.asc(), Staff.id.asc())
    )
    if allowed is not None:
        stmt = stmt.where(Company.id.in_(allowed))
    if not include_fired:
        stmt = stmt.where(Staff.fired == 0)

    rows = (await db.execute(stmt)).all()
    return [
        {
            'company_id': row.company_id,
            'company_title': row.company_title,
            'staff_id': row.staff_id,
            'staff_name': row.staff_name,
            'position': row.position,
            'user_id': row.user_id,
            'fired': int(row.fired or 0),
            'working': int((row.fired or 0) == 0),
            'bookable': int(bool(row.bookable)),
        }
        for row in rows
        if (
            not _is_waitlist_staff_name(row.staff_name)
            and not _is_admin_placeholder_staff_name(row.staff_name)
        )
    ]


async def fetch_branches(db: AsyncSession) -> list[dict[str, Any]]:
    allowed = await branch_company_ids(db)
    stmt = select(Company).order_by(Company.id.asc())
    if allowed is not None:
        stmt = stmt.where(Company.id.in_(allowed))
    rows = (await db.execute(stmt)).scalars().all()
    return [{'id': c.id, 'title': c.title, 'group_id': c.group_id} for c in rows]
