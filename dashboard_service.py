"""Aggregated metrics for the product dashboard (JSON for SPA / Chart.js)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Appointment,
    Comment,
    Company,
    GoodTransaction,
    PlanMetric,
    PortalBranch,
    Service,
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


def _date_time_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return datetime.combine(start, time.min), datetime.combine(end, time.max)


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
    service_revenue = float(row.revenue or 0)
    goods_revenue = await _goods_revenue_total(db, dr, company_id, staff_id)
    return {
        'revenue': service_revenue + goods_revenue,
        'service_revenue': service_revenue,
        'goods_revenue': goods_revenue,
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
            'service_revenue': cur['service_revenue'],
            'goods_revenue': cur['goods_revenue'],
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
    svc_stmt = (
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
    )

    goods_day = func.date(GoodTransaction.date)
    goods_stmt = (
        select(
            goods_day.label('d'),
            func.coalesce(func.sum(GoodTransaction.cost), 0.0).label('revenue'),
        )
        .where(_goods_revenue_filters(start, end, company_id))
        .group_by(goods_day)
    )

    svc_rows = (await db.execute(svc_stmt)).all()
    goods_rows = (await db.execute(goods_stmt)).all()

    by_date: dict[date, dict[str, float | int]] = {}
    for r in svc_rows:
        by_date.setdefault(r.d, {'service_revenue': 0.0, 'goods_revenue': 0.0, 'appointments': 0})
        by_date[r.d]['service_revenue'] = float(r.revenue or 0)
        by_date[r.d]['appointments'] = int(r.appointments or 0)
    for r in goods_rows:
        by_date.setdefault(r.d, {'service_revenue': 0.0, 'goods_revenue': 0.0, 'appointments': 0})
        by_date[r.d]['goods_revenue'] = float(r.revenue or 0)

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
    stmt = (
        select(
            func.coalesce(func.sum(GoodTransaction.amount), 0.0).label('qty'),
            func.coalesce(func.sum(GoodTransaction.cost), 0.0).label('revenue'),
        )
        .where(_goods_revenue_filters(start, end, company_id, staff_id))
    )
    row = (await db.execute(stmt)).one()
    return {
        'cosmo_qty': float(row.qty or 0),
        'cosmo_sum': float(row.revenue or 0),
    }


async def _reviews_count(
    db: AsyncSession,
    start: date,
    end: date,
    company_id: int,
    staff_id: Optional[int] = None,
) -> float:
    start_dt, end_dt = _date_time_bounds(start, end)
    filters = [
        Comment.company_id == company_id,
        Comment.date >= start_dt,
        Comment.date <= end_dt,
    ]
    if staff_id is not None:
        filters.append(Comment.master_id == staff_id)
    stmt = (
        select(func.count(Comment.id))
        .where(*filters)
    )
    return float((await db.scalar(stmt)) or 0)


async def _opz_count(
    db: AsyncSession,
    start: date,
    end: date,
    company_id: int,
    staff_id: Optional[int] = None,
    created_user_id: Optional[int] = None,
) -> float:
    visit_filters = [
        Appointment.company_id == company_id,
        Appointment.attendance > 0,
        Appointment.client_id.is_not(None),
        Appointment.date >= start,
        Appointment.date <= end,
    ]
    if staff_id is not None:
        visit_filters.append(Appointment.staff_id == staff_id)
    visits_stmt = (
        select(Appointment.id, Appointment.company_id, Appointment.client_id, Appointment.date)
        .where(*visit_filters)
    )
    visits = (await db.execute(visits_stmt)).all()
    if not visits:
        return 0.0

    create_start = datetime.combine(start, time.min)
    create_end = datetime.combine(end + timedelta(days=1), time.max)
    candidate_filters = [
        Appointment.company_id == company_id,
        Appointment.client_id.is_not(None),
        Appointment.create_date >= create_start,
        Appointment.create_date <= create_end,
        Appointment.date > start,
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
    candidates_by_client: dict[tuple[int, int], list[Any]] = {}
    for candidate in candidates:
        candidates_by_client.setdefault((candidate.company_id, candidate.client_id), []).append(candidate)

    booked_clients: set[tuple[int, int]] = set()
    for visit in visits:
        visit_date = visit.date
        expected_create_dates = {visit_date, visit_date + timedelta(days=1)}
        for candidate in candidates_by_client.get((visit.company_id, visit.client_id), []):
            if candidate.id == visit.id or candidate.create_date is None:
                continue
            if candidate.date <= visit_date:
                continue
            if candidate.create_date.date() in expected_create_dates:
                booked_clients.add((visit.company_id, visit.client_id))
                break

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
        'reviews_qty': await _reviews_count(db, start, end, company_id, staff_id),
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


async def _fetch_company_staff(db: AsyncSession, company_id: int) -> list[Any]:
    stmt = (
        select(Staff.id, Staff.name, Staff.position, Staff.user_id)
        .where(Staff.company_id == company_id)
        .order_by(Staff.position.asc(), Staff.name.asc())
    )
    return list((await db.execute(stmt)).all())


async def fetch_plan_fact(
    db: AsyncSession,
    start: date,
    end: date,
    company_id: Optional[int] = None,
) -> dict[str, Any]:
    branches = await fetch_branches(db)
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
                'metrics': list(PLAN_FACT_METRICS),
                'metric_sets': _metric_sets_payload(),
                'groups': [],
            }

        branch_id = company_ids[0]
        branch = branches[0]
        staff_rows = await _fetch_company_staff(db, branch_id)
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


async def fetch_branches(db: AsyncSession) -> list[dict[str, Any]]:
    allowed = await branch_company_ids(db)
    stmt = select(Company).order_by(Company.id.asc())
    if allowed is not None:
        stmt = stmt.where(Company.id.in_(allowed))
    rows = (await db.execute(stmt)).scalars().all()
    return [{'id': c.id, 'title': c.title, 'group_id': c.group_id} for c in rows]
