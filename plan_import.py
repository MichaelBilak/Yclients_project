"""Import manually maintained branch plan values from a Google Sheets CSV export."""

from __future__ import annotations

import csv
import io
import asyncio
import re
import urllib.request
from calendar import monthrange
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import PLAN_SHEET_CSV_URL
from models import Company, PlanMetric


METRIC_COLUMN_ALIASES = {
    'revenue': ('выручка', 'revenue'),
    'avg_check_total': ('сч общий', 'сч', 'avg_check_total', 'average_check'),
    'clients': ('кол-во клиентов', 'количество клиентов', 'клиенты', 'clients'),
    'wax_qty': ('воск, шт', 'воск', 'wax_qty'),
    'camouflage_qty': ('камуфляж, шт', 'камуфляж', 'camouflage_qty'),
    'face_care_qty': ('уход лицо, шт', 'уход лицо', 'face_care_qty'),
    'head_care_qty': ('уход голова, шт', 'уход голова', 'head_care_qty'),
    'cosmo_qty': ('космо, шт', 'космо шт', 'cosmo_qty'),
    'cosmo_sum': ('космо сумм.', 'космо сумма', 'космо сумм', 'cosmo_sum'),
    'reviews_qty': ('отзывы, шт', 'отзывы', 'reviews_qty'),
    'opz_qty': ('опз, шт', 'опз шт', 'opz_qty'),
    'opz_pct': ('опз,%', 'опз %', 'опз процент', 'opz_pct'),
    'extra_services_pct': ('% доп.услуг', 'доп.услуг,%', 'доп услуги %', 'extra_services_pct'),
}

PERIOD_START_ALIASES = ('period_start', 'date_from', 'start_date', 'начало периода', 'с')
PERIOD_END_ALIASES = ('period_end', 'date_to', 'end_date', 'конец периода', 'по')
MONTH_ALIASES = ('month', 'месяц', 'period', 'период')
COMPANY_ID_ALIASES = ('company_id', 'yclients_company_id', 'id филиала')
BRANCH_ALIASES = ('branch', 'branch_name', 'филиал', 'бш', 'салон')
NETWORK_NAMES = {'сеть', 'итого', 'total', 'network'}


def _normalize(value: Any) -> str:
    text = str(value or '').strip().lower().replace('ё', 'е')
    text = text.replace('\xa0', ' ')
    text = re.sub(r'\s+', ' ', text)
    return text


def _find_value(row: dict[str, str], aliases: tuple[str, ...]) -> str:
    normalized = {_normalize(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_normalize(alias))
        if value not in (None, ''):
            return value
    return ''


def _parse_date(value: str) -> date:
    raw = str(value or '').strip()
    for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    raise ValueError(f'Unsupported date format: {value}')


def _parse_period(row: dict[str, str]) -> tuple[date, date]:
    start_value = _find_value(row, PERIOD_START_ALIASES)
    end_value = _find_value(row, PERIOD_END_ALIASES)
    if start_value and end_value:
        return _parse_date(start_value), _parse_date(end_value)

    month_value = _find_value(row, MONTH_ALIASES).strip()
    if re.fullmatch(r'\d{4}-\d{2}', month_value):
        year, month = [int(part) for part in month_value.split('-')]
        return date(year, month, 1), date(year, month, monthrange(year, month)[1])

    raise ValueError('Plan row must contain period_start/period_end or month=YYYY-MM')


def _parse_number(value: str) -> float | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    normalized = (
        raw.replace('\xa0', '')
        .replace(' ', '')
        .replace('%', '')
        .replace('₽', '')
    )
    if ',' in normalized and '.' in normalized:
        normalized = normalized.replace(',', '')
    elif normalized.count(',') > 1:
        normalized = normalized.replace(',', '')
    elif re.fullmatch(r'-?\d{1,3},\d{3}', normalized):
        normalized = normalized.replace(',', '')
    else:
        normalized = normalized.replace(',', '.')
    try:
        return float(normalized)
    except ValueError:
        return None


def _csv_text_from_url(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode('utf-8-sig')


async def import_plan_sheet_csv(db: AsyncSession, csv_text: str, source: str = 'google_sheet') -> dict[str, Any]:
    company_rows = (await db.execute(select(Company.id, Company.title))).all()
    companies_by_title = {_normalize(row.title): int(row.id) for row in company_rows}
    company_ids = {int(row.id) for row in company_rows}

    metric_headers = {
        _normalize(alias): code
        for code, aliases in METRIC_COLUMN_ALIASES.items()
        for alias in aliases
    }

    reader = csv.DictReader(io.StringIO(csv_text))
    now = datetime.utcnow()
    imported = 0
    skipped: list[str] = []

    for index, row in enumerate(reader, start=2):
        try:
            period_start, period_end = _parse_period(row)
        except ValueError as exc:
            skipped.append(f'row {index}: {exc}')
            continue

        company_id_value = _find_value(row, COMPANY_ID_ALIASES)
        branch_value = _find_value(row, BRANCH_ALIASES)
        if _normalize(branch_value) in NETWORK_NAMES:
            continue

        company_id_text = company_id_value.strip()
        company_id = int(company_id_text) if company_id_text.isdigit() else None
        if company_id is None and branch_value:
            company_id = companies_by_title.get(_normalize(branch_value))
        if company_id not in company_ids:
            skipped.append(f'row {index}: unknown company {branch_value or company_id_value}')
            continue

        values: dict[str, float] = {}
        for header, raw_value in row.items():
            metric_code = metric_headers.get(_normalize(header))
            if not metric_code:
                continue
            number = _parse_number(raw_value)
            if number is not None:
                values[metric_code] = number

        if not values:
            skipped.append(f'row {index}: no metric values')
            continue

        await db.execute(
            delete(PlanMetric).where(
                PlanMetric.period_start == period_start,
                PlanMetric.period_end == period_end,
                PlanMetric.company_id == company_id,
                PlanMetric.metric_code.in_(list(values.keys())),
            )
        )
        for metric_code, value in values.items():
            db.add(
                PlanMetric(
                    period_start=period_start,
                    period_end=period_end,
                    company_id=company_id,
                    metric_code=metric_code,
                    value=value,
                    source=source,
                    updated_at=now,
                )
            )
            imported += 1

    await db.commit()
    return {'imported': imported, 'skipped': skipped}


async def import_plan_sheet_from_config(db: AsyncSession) -> dict[str, Any]:
    if not PLAN_SHEET_CSV_URL:
        return {'imported': 0, 'skipped': ['PLAN_SHEET_CSV_URL is not configured']}
    csv_text = await asyncio.to_thread(_csv_text_from_url, PLAN_SHEET_CSV_URL)
    return await import_plan_sheet_csv(db, csv_text, source='google_sheet')
