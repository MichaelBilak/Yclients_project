"""Import manually maintained branch and staff plan values from a Google Sheets CSV export."""

from __future__ import annotations

import csv
import io
import asyncio
import re
import urllib.parse
import urllib.request
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import PLAN_SHEET_CSV_URL, SERVICES_SHEET_CSV_URL
from models import Company, PlanMetric, Service, ServiceLabel, Staff
from plan_config import (
    RAW_PLAN_FACT_CODES,
    STAFF_CATEGORY_METRIC_CODES,
    normalize_staff_category,
)


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
    'opz_qty': ('опз, шт', 'опз шт', 'opz_qty'),
    'opz_pct': ('опз,%', 'опз %', 'опз процент', 'opz_pct'),
    'extra_services_pct': ('% доп.услуг', 'доп.услуг,%', 'доп услуги %', 'extra_services_pct'),
}

RETIRED_PLAN_METRIC_CODES = {'reviews_qty'}

PERIOD_START_ALIASES = ('period_start', 'date_from', 'start_date', 'начало периода', 'с')
PERIOD_END_ALIASES = ('period_end', 'date_to', 'end_date', 'конец периода', 'по')
MONTH_ALIASES = ('month', 'месяц', 'period', 'период')
COMPANY_ID_ALIASES = ('company_id', 'yclients_company_id', 'id филиала')
BRANCH_ALIASES = ('branch', 'branch_name', 'филиал', 'бш', 'салон')
STAFF_ID_ALIASES = ('staff_id', 'stuff_id', 'yclients_staff_id', 'employee_id', 'id сотрудника', 'id работника')
STAFF_NAME_ALIASES = ('staff', 'staff_name', 'stuff_name', 'employee', 'employee_name', 'сотрудник', 'работник')
STAFF_CATEGORY_ALIASES = ('staff_category', 'category', 'position', 'role', 'должность', 'роль', 'категория', 'тип сотрудника')
NETWORK_NAMES = {'сеть', 'итого', 'total', 'network'}
VALIDATION_TOLERANCE = 0.01

SERVICE_ID_ALIASES = ('service_id', 'yclients_service_id', 'id услуги', 'id', 'service id')
SERVICE_TITLE_ALIASES = ('service', 'service_title', 'title', 'услуга', 'название услуги')
SERVICE_EXTRA_ALIASES = (
    'is_extra',
    'extra_service',
    'additional_service',
    'доп услуга',
    'доп. услуга',
    'доп услуги',
    'доп. услуги',
    'метка доп услуг',
)
SERVICE_TAG_ALIASES = ('tag', 'label', 'метка', 'тег')
TRUE_MARKERS = {'1', 'true', 'yes', 'y', 'да', 'истина', 'доп', 'доп услуга', 'доп услуги', 'extra', 'additional', 'x', '+'}
FALSE_MARKERS = {
    '0',
    'false',
    'no',
    'n',
    'нет',
    'ложь',
    'обычная',
    'основная',
    'не доп',
    'не доп услуга',
    'не доп услуги',
    'standard',
    'base',
    '-',
}


@dataclass(frozen=True)
class ParsedPlanRow:
    row_index: int
    period_start: date
    period_end: date
    company_id: int | None
    staff_id: int | None
    staff_category: str | None
    values: dict[str, float]
    metric_codes: frozenset[str]
    scope: str


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


def _parse_marker(value: str) -> bool | None:
    text = _normalize(value)
    if not text:
        return None
    if text in TRUE_MARKERS:
        return True
    if text in FALSE_MARKERS:
        return False
    if 'доп' in text or 'extra' in text or 'additional' in text:
        return True
    return None


def _branch_or_staff_filter(period_start: date, period_end: date, company_id: int, staff_id: int | None):
    parts = [
        PlanMetric.period_start == period_start,
        PlanMetric.period_end == period_end,
        PlanMetric.company_id == company_id,
    ]
    if staff_id is None:
        parts.append(PlanMetric.staff_id.is_(None))
    else:
        parts.append(PlanMetric.staff_id == staff_id)
    return parts


def _validation_warning(
    scope: str,
    key: tuple[Any, ...],
    metric_code: str,
    expected: float | None,
    actual: float,
) -> str:
    expected_text = 'нет плана' if expected is None else f'{expected:g}'
    return (
        f'{scope} {key}: metric {metric_code} mismatch '
        f'(expected {expected_text}, calculated {actual:g})'
    )


def _sum_values(rows: list[ParsedPlanRow]) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in rows:
        for code in RAW_PLAN_FACT_CODES:
            if code in row.values:
                values[code] = values.get(code, 0.0) + float(row.values[code] or 0)
    return values


def _metric_codes(rows: list[ParsedPlanRow]) -> set[str]:
    codes: set[str] = set()
    for row in rows:
        codes.update(row.metric_codes)
    return codes


async def _save_plan_values(
    db: AsyncSession,
    *,
    period_start: date,
    period_end: date,
    company_id: int,
    staff_id: int | None,
    staff_category: str | None,
    metric_codes: set[str] | frozenset[str],
    values: dict[str, float],
    source: str,
    updated_at: datetime,
) -> int:
    if not metric_codes:
        return 0

    await db.execute(
        delete(PlanMetric).where(
            *_branch_or_staff_filter(period_start, period_end, company_id, staff_id),
            PlanMetric.metric_code.in_(list(set(metric_codes) | RETIRED_PLAN_METRIC_CODES)),
        )
    )

    imported = 0
    for metric_code, value in values.items():
        db.add(
            PlanMetric(
                period_start=period_start,
                period_end=period_end,
                company_id=company_id,
                staff_id=staff_id,
                staff_category=staff_category,
                metric_code=metric_code,
                value=value,
                source=source,
                updated_at=updated_at,
            )
        )
        imported += 1
    return imported


async def _derive_missing_branch_plans(
    db: AsyncSession,
    parsed_rows: list[ParsedPlanRow],
    *,
    source: str,
    updated_at: datetime,
) -> int:
    branch_keys = {
        (row.period_start, row.period_end, row.company_id)
        for row in parsed_rows
        if row.scope == 'branch' and row.company_id is not None
    }
    staff_by_branch: dict[tuple[date, date, int], list[ParsedPlanRow]] = {}
    for row in parsed_rows:
        if row.scope == 'staff' and row.company_id is not None:
            staff_by_branch.setdefault((row.period_start, row.period_end, row.company_id), []).append(row)

    imported = 0
    for key, rows in staff_by_branch.items():
        if key in branch_keys:
            continue
        period_start, period_end, company_id = key
        metric_codes = _metric_codes(rows) & RAW_PLAN_FACT_CODES
        values = _sum_values(rows)
        imported += await _save_plan_values(
            db,
            period_start=period_start,
            period_end=period_end,
            company_id=company_id,
            staff_id=None,
            staff_category=None,
            metric_codes=metric_codes,
            values=values,
            source=f'{source}:staff_sum',
            updated_at=updated_at,
        )
        parsed_rows.append(
            ParsedPlanRow(
                row_index=0,
                period_start=period_start,
                period_end=period_end,
                company_id=company_id,
                staff_id=None,
                staff_category=None,
                values=values,
                metric_codes=frozenset(metric_codes),
                scope='branch',
            )
        )
    return imported


def _validate_plan_totals(parsed_rows: list[ParsedPlanRow]) -> list[str]:
    warnings: list[str] = []

    branch_rows = [row for row in parsed_rows if row.scope == 'branch']
    staff_rows = [row for row in parsed_rows if row.scope == 'staff']
    network_rows = [row for row in parsed_rows if row.scope == 'network']

    branch_by_key = {
        (row.period_start, row.period_end, row.company_id): row
        for row in branch_rows
        if row.company_id is not None
    }
    staff_by_branch: dict[tuple[date, date, int], list[ParsedPlanRow]] = {}
    for row in staff_rows:
        if row.company_id is None:
            continue
        staff_by_branch.setdefault((row.period_start, row.period_end, row.company_id), []).append(row)

    for key, rows in staff_by_branch.items():
        branch = branch_by_key.get(key)
        branch_values = branch.values if branch else {}
        staff_values = _sum_values(rows)
        for metric_code, staff_value in staff_values.items():
            branch_value = branch_values.get(metric_code)
            if branch_value is None or abs(branch_value - staff_value) > VALIDATION_TOLERANCE:
                warnings.append(_validation_warning('branch staff total', key, metric_code, branch_value, staff_value))

    branches_by_period: dict[tuple[date, date], list[ParsedPlanRow]] = {}
    for row in branch_rows:
        branches_by_period.setdefault((row.period_start, row.period_end), []).append(row)

    for row in network_rows:
        key = (row.period_start, row.period_end)
        branch_values = _sum_values(branches_by_period.get(key, []))
        for metric_code, network_value in row.values.items():
            if metric_code not in RAW_PLAN_FACT_CODES:
                continue
            branch_value = branch_values.get(metric_code, 0.0)
            if abs(network_value - branch_value) > VALIDATION_TOLERANCE:
                warnings.append(_validation_warning('network branch total', key, metric_code, network_value, branch_value))

    return warnings


def _csv_text_from_url(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode('utf-8-sig')


def _sheet_csv_url_from_spreadsheet_url(url: str, sheet_name: str) -> str:
    match = re.search(r'/spreadsheets/d/([^/]+)', url or '')
    if not match:
        return ''
    spreadsheet_id = match.group(1)
    query = urllib.parse.urlencode({'tqx': 'out:csv', 'sheet': sheet_name})
    return f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?{query}'


async def import_plan_sheet_csv(db: AsyncSession, csv_text: str, source: str = 'google_sheet') -> dict[str, Any]:
    company_rows = (await db.execute(select(Company.id, Company.title))).all()
    companies_by_title = {_normalize(row.title): int(row.id) for row in company_rows}
    company_ids = {int(row.id) for row in company_rows}
    staff_rows = (await db.execute(select(Staff.id, Staff.name, Staff.company_id, Staff.position))).all()
    staff_by_id = {int(row.id): row for row in staff_rows}
    staff_by_company_name = {
        (int(row.company_id), _normalize(row.name)): row
        for row in staff_rows
    }

    metric_headers = {
        _normalize(alias): code
        for code, aliases in METRIC_COLUMN_ALIASES.items()
        for alias in aliases
    }

    reader = csv.DictReader(io.StringIO(csv_text))
    now = datetime.utcnow()
    imported = 0
    skipped: list[str] = []
    warnings: list[str] = []
    parsed_rows: list[ParsedPlanRow] = []

    for index, row in enumerate(reader, start=2):
        try:
            period_start, period_end = _parse_period(row)
        except ValueError as exc:
            skipped.append(f'row {index}: {exc}')
            continue

        company_id_value = _find_value(row, COMPANY_ID_ALIASES)
        branch_value = _find_value(row, BRANCH_ALIASES)
        is_network = _normalize(branch_value) in NETWORK_NAMES

        company_id_text = company_id_value.strip()
        company_id = int(company_id_text) if company_id_text.isdigit() else None
        if company_id is None and branch_value:
            company_id = companies_by_title.get(_normalize(branch_value))

        staff_id_value = _find_value(row, STAFF_ID_ALIASES)
        staff_name_value = _find_value(row, STAFF_NAME_ALIASES)
        staff_id_text = staff_id_value.strip()
        staff_id = int(staff_id_text) if staff_id_text.isdigit() else None
        staff_row = None
        if staff_id is not None:
            staff_row = staff_by_id.get(staff_id)
            if staff_row is None:
                skipped.append(f'row {index}: unknown staff {staff_id}')
                continue
            if company_id is not None and int(staff_row.company_id) != company_id:
                skipped.append(f'row {index}: staff {staff_id} does not belong to company {company_id}')
                continue
            company_id = int(staff_row.company_id)
        elif staff_name_value and company_id is not None:
            staff_row = staff_by_company_name.get((company_id, _normalize(staff_name_value)))
            if staff_row is None:
                skipped.append(f'row {index}: unknown staff {staff_name_value}')
                continue
            staff_id = int(staff_row.id)

        if not is_network and company_id not in company_ids:
            skipped.append(f'row {index}: unknown company {branch_value or company_id_value}')
            continue

        staff_category = None
        if staff_id is not None:
            staff_category = normalize_staff_category(_find_value(row, STAFF_CATEGORY_ALIASES))
            if staff_category is None and staff_row is not None:
                staff_category = normalize_staff_category(staff_row.position)
            if staff_category not in STAFF_CATEGORY_METRIC_CODES:
                skipped.append(f'row {index}: unknown staff category for staff {staff_id}')
                continue

        values: dict[str, float] = {}
        row_metric_codes: set[str] = set()
        for header, raw_value in row.items():
            metric_code = metric_headers.get(_normalize(header))
            if not metric_code:
                continue
            row_metric_codes.add(metric_code)
            number = _parse_number(raw_value)
            if number is not None:
                values[metric_code] = number

        if staff_category:
            allowed_codes = set(STAFF_CATEGORY_METRIC_CODES[staff_category])
            invalid_codes = sorted(set(values) - allowed_codes)
            if invalid_codes:
                warnings.append(f'row {index}: skipped metrics not applicable to {staff_category}: {", ".join(invalid_codes)}')
            values = {
                metric_code: value
                for metric_code, value in values.items()
                if metric_code in allowed_codes
            }

        if not values:
            skipped.append(f'row {index}: no metric values')
            continue

        scope = 'network' if is_network else ('staff' if staff_id is not None else 'branch')
        parsed_row = ParsedPlanRow(
            row_index=index,
            period_start=period_start,
            period_end=period_end,
            company_id=company_id,
            staff_id=staff_id,
            staff_category=staff_category,
            values=values,
            metric_codes=frozenset(row_metric_codes),
            scope=scope,
        )
        parsed_rows.append(parsed_row)

        if scope == 'network':
            continue

        imported += await _save_plan_values(
            db,
            period_start=period_start,
            period_end=period_end,
            company_id=company_id,
            staff_id=staff_id,
            staff_category=staff_category,
            metric_codes=row_metric_codes,
            values=values,
            source=source,
            updated_at=now,
        )

    imported += await _derive_missing_branch_plans(db, parsed_rows, source=source, updated_at=now)
    await db.commit()
    warnings.extend(_validate_plan_totals(parsed_rows))
    return {'imported': imported, 'skipped': skipped, 'warnings': warnings}


async def import_services_sheet_csv(
    db: AsyncSession,
    csv_text: str,
    source: str = 'google_sheet:services',
) -> dict[str, Any]:
    service_rows = (await db.execute(select(Service.id, Service.title, Service.company_id))).all()
    services_by_id = {int(row.id): row for row in service_rows}
    services_by_company_title = {
        (int(row.company_id), _normalize(row.title)): row
        for row in service_rows
    }
    services_by_title: dict[str, list[Any]] = {}
    for row in service_rows:
        services_by_title.setdefault(_normalize(row.title), []).append(row)

    company_rows = (await db.execute(select(Company.id, Company.title))).all()
    companies_by_title = {_normalize(row.title): int(row.id) for row in company_rows}

    reader = csv.DictReader(io.StringIO(csv_text))
    now = datetime.utcnow()
    skipped: list[str] = []
    warnings: list[str] = []
    labels_by_service_id: dict[int, ServiceLabel] = {}
    processed_markers = 0

    for index, row in enumerate(reader, start=2):
        service_id_value = _find_value(row, SERVICE_ID_ALIASES).strip()
        service_id = int(service_id_value) if service_id_value.isdigit() else None
        service_row = services_by_id.get(service_id) if service_id is not None else None
        matched_services = [service_row] if service_row is not None else []
        title_value = _find_value(row, SERVICE_TITLE_ALIASES)

        if service_row is None:
            company_id_value = _find_value(row, COMPANY_ID_ALIASES).strip()
            company_id = int(company_id_value) if company_id_value.isdigit() else None
            if company_id is None:
                branch_value = _find_value(row, BRANCH_ALIASES)
                company_id = companies_by_title.get(_normalize(branch_value))
            if company_id is not None and title_value:
                service_row = services_by_company_title.get((company_id, _normalize(title_value)))
                matched_services = [service_row] if service_row is not None else []
            elif title_value:
                matched_services = services_by_title.get(_normalize(title_value), [])

        if not matched_services:
            skipped.append(f'row {index}: unknown service {service_id_value or _find_value(row, SERVICE_TITLE_ALIASES)}')
            continue

        marker_value = _find_value(row, SERVICE_EXTRA_ALIASES) or _find_value(row, SERVICE_TAG_ALIASES)
        is_extra = _parse_marker(marker_value)
        if is_extra is None:
            skipped.append(f'row {index}: no extra-service marker')
            continue

        processed_markers += 1
        if is_extra:
            for matched_service in matched_services:
                service_id = int(matched_service.id)
                labels_by_service_id[service_id] = ServiceLabel(
                    service_id=service_id,
                    company_id=int(matched_service.company_id),
                    is_extra=True,
                    source=source,
                    updated_at=now,
                )

    if processed_markers == 0:
        warnings.append('services sheet has no rows with extra-service marker; labels unchanged')
        return {'imported': 0, 'processed': 0, 'skipped': skipped, 'warnings': warnings}

    await db.execute(delete(ServiceLabel))
    imported = 0
    for label in labels_by_service_id.values():
        db.add(label)
        imported += 1
    await db.commit()
    return {
        'imported': imported,
        'processed': processed_markers,
        'skipped': skipped,
        'warnings': warnings,
    }


async def import_services_sheet_from_config(db: AsyncSession) -> dict[str, Any]:
    services_url = SERVICES_SHEET_CSV_URL or _sheet_csv_url_from_spreadsheet_url(
        PLAN_SHEET_CSV_URL,
        'services',
    )
    if not services_url:
        return {'imported': 0, 'processed': 0, 'skipped': ['services sheet CSV URL is not configured'], 'warnings': []}

    try:
        csv_text = await asyncio.to_thread(_csv_text_from_url, services_url)
    except Exception as exc:
        return {
            'imported': 0,
            'processed': 0,
            'skipped': [f'services sheet is unavailable: {exc}'],
            'warnings': [],
        }
    return await import_services_sheet_csv(db, csv_text, source='google_sheet:services')


async def import_plan_sheet_from_config(db: AsyncSession) -> dict[str, Any]:
    if not PLAN_SHEET_CSV_URL:
        return {'imported': 0, 'skipped': ['PLAN_SHEET_CSV_URL is not configured']}
    csv_text = await asyncio.to_thread(_csv_text_from_url, PLAN_SHEET_CSV_URL)
    result = await import_plan_sheet_csv(db, csv_text, source='google_sheet')
    result['services'] = await import_services_sheet_from_config(db)
    return result
