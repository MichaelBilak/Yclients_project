"""Dashboard JSON API (product portal metrics)."""

from datetime import date, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import api
from plan_import import import_plan_sheet_csv
from api import app
from models import Appointment, Client, Comment, Company, GoodTransaction, Group, PlanMetric, Staff, Transaction


@pytest.mark.asyncio
async def test_dashboard_bundle_requires_api_key(async_session, monkeypatch):
    monkeypatch.setattr(api, 'API_KEY', 'k')

    async def override_db():
        yield async_session

    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        r = await client.get(
            '/dashboard/bundle',
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31'},
        )
        assert r.status_code == 401
        r2 = await client.get(
            '/dashboard/bundle',
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31'},
            headers={'X-API-Key': 'k'},
        )
        assert r2.status_code == 200
        body = r2.json()
        assert body['success'] is True
        assert 'summary' in body['data']
        assert 'revenue_daily' in body['data']
        assert 'top_services' in body['data']

    app.dependency_overrides.clear()
    monkeypatch.setattr(api, 'API_KEY', '')


@pytest.mark.asyncio
async def test_dashboard_summary_revenue_and_change(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon', group_id=1))
    async_session.add(Staff(id=1, name='Master', company_id=1))
    async_session.add(Client(id=1, name='Client', company_id=1, visits_count=1, last_visit_date=date(2025, 1, 10)))
    await async_session.flush()
    async_session.add_all([
        Appointment(
            id=1,
            company_id=1,
            staff_id=1,
            client_id=1,
            date=date(2025, 1, 10),
            datetime=datetime(2025, 1, 10, 12, 0, 0),
            create_date=datetime(2025, 1, 9, 12, 0, 0),
            seance_length=3600,
            attendance=1,
        ),
        Appointment(
            id=2,
            company_id=1,
            staff_id=1,
            client_id=1,
            date=date(2024, 12, 20),
            datetime=datetime(2024, 12, 20, 12, 0, 0),
            create_date=datetime(2024, 12, 19, 12, 0, 0),
            seance_length=3600,
            attendance=1,
        ),
    ])
    await async_session.flush()
    async_session.add_all([
        Transaction(id=1, appointment_id=1, service_id=10, service_title='Cut', cost=1000.0, first_cost=1000.0, amount=1, company_id=1),
        Transaction(id=2, appointment_id=2, service_id=10, service_title='Cut', cost=500.0, first_cost=500.0, amount=1, company_id=1),
    ])
    await async_session.commit()

    async def override_db():
        yield async_session

    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        r = await client.get(
            '/dashboard/widget/summary',
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31'},
        )
    app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()['data']
    assert data['revenue']['total'] == 1000.0
    assert data['revenue']['change_pct'] == 100.0
    assert data['appointments_breakdown']['attended'] == 1


@pytest.mark.asyncio
async def test_dashboard_branches_respects_portal_allowlist(async_session, monkeypatch):
    import dashboard_service

    async_session.add(Group(id=1, title='G'))
    async_session.add(Company(id=1, title='A', group_id=1))
    async_session.add(Company(id=2, title='B', group_id=1))
    await async_session.commit()

    async def fake_ids(_db):
        return [2]

    monkeypatch.setattr(dashboard_service, 'branch_company_ids', fake_ids)

    async def override_db():
        yield async_session

    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        r = await client.get('/dashboard/branches')
    app.dependency_overrides.clear()

    assert r.status_code == 200
    rows = r.json()['data']
    assert len(rows) == 1
    assert rows[0]['id'] == 2


@pytest.mark.asyncio
async def test_dashboard_plan_fact_uses_plan_and_fact_formulas(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon', group_id=1))
    async_session.add(Staff(id=1, name='Master', company_id=1))
    async_session.add(Client(id=1, name='Client', company_id=1, visits_count=1, last_visit_date=date(2025, 1, 10)))
    await async_session.flush()

    async_session.add_all([
        Appointment(
            id=1,
            company_id=1,
            staff_id=1,
            client_id=1,
            date=date(2025, 1, 10),
            datetime=datetime(2025, 1, 10, 12, 0, 0),
            create_date=datetime(2025, 1, 9, 12, 0, 0),
            seance_length=3600,
            attendance=1,
        ),
        Appointment(
            id=2,
            company_id=1,
            staff_id=1,
            client_id=1,
            date=date(2025, 2, 10),
            datetime=datetime(2025, 2, 10, 12, 0, 0),
            create_date=datetime(2025, 1, 10, 18, 0, 0),
            seance_length=3600,
            attendance=0,
        ),
    ])
    await async_session.flush()

    async_session.add_all([
        Transaction(
            id=1,
            appointment_id=1,
            service_id=10,
            service_title='воск',
            cost=1000.0,
            first_cost=1000.0,
            amount=1,
            company_id=1,
        ),
        Transaction(
            id=2,
            appointment_id=1,
            service_id=11,
            service_title='камуфляж',
            cost=500.0,
            first_cost=500.0,
            amount=2,
            company_id=1,
        ),
        GoodTransaction(
            id=1,
            document_id=1,
            type_id=1,
            amount=3.0,
            cost=1500.0,
            company_id=1,
            date=datetime(2025, 1, 11, 12, 0, 0),
        ),
        Comment(
            id=1,
            type='review',
            master_id=1,
            text='ok',
            date=datetime(2025, 1, 12, 12, 0, 0),
            rating=5.0,
            company_id=1,
        ),
    ])

    now = datetime(2025, 1, 1, 0, 0, 0)
    for code, value in {
        'revenue': 7000.0,
        'clients': 2.0,
        'wax_qty': 2.0,
        'camouflage_qty': 2.0,
        'cosmo_qty': 4.0,
        'cosmo_sum': 2000.0,
        'reviews_qty': 2.0,
        'opz_qty': 2.0,
    }.items():
        async_session.add(
            PlanMetric(
                period_start=date(2025, 1, 1),
                period_end=date(2025, 1, 31),
                company_id=1,
                metric_code=code,
                value=value,
                updated_at=now,
            )
        )
    await async_session.commit()

    async def override_db():
        yield async_session

    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        r = await client.get(
            '/dashboard/widget/plan_fact',
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31', 'company_id': 1},
        )
        r_partial = await client.get(
            '/dashboard/widget/plan_fact',
            params={'start_date': '2025-01-15', 'end_date': '2025-01-20', 'company_id': 1},
        )
    app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()['data']
    assert data['plan_period'] == {'start': '2025-01-01', 'end': '2025-01-31'}
    assert data['groups'][0]['title'] == 'Salon'

    cells = {cell['code']: cell for cell in data['groups'][0]['metrics']}
    assert cells['revenue']['fact'] == 3500.0
    assert cells['revenue']['completion_pct'] == 50.0
    assert cells['avg_check_total']['fact'] == 3500.0
    assert cells['clients']['fact'] == 1.0
    assert cells['wax_qty']['fact'] == 1.0
    assert cells['camouflage_qty']['fact'] == 2.0
    assert cells['cosmo_qty']['fact'] == 3.0
    assert cells['cosmo_sum']['fact'] == 1500.0
    assert cells['reviews_qty']['fact'] == 1.0
    assert cells['opz_qty']['fact'] == 1.0
    assert cells['opz_pct']['fact'] == 100.0
    assert cells['extra_services_pct']['fact'] == 300.0

    assert r_partial.status_code == 200
    partial_data = r_partial.json()['data']
    assert partial_data['period'] == {'start': '2025-01-15', 'end': '2025-01-20'}
    assert partial_data['plan_period'] == {'start': '2025-01-01', 'end': '2025-01-31'}
    partial_cells = {cell['code']: cell for cell in partial_data['groups'][0]['metrics']}
    assert partial_cells['revenue']['plan'] == 7000.0
    assert partial_cells['revenue']['fact'] == 0.0


@pytest.mark.asyncio
async def test_plan_sheet_csv_imports_wide_branch_rows(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon', group_id=1))
    await async_session.commit()

    result = await import_plan_sheet_csv(
        async_session,
        'month,branch,выручка,кол-во клиентов,воск\n'
        '2025-01,Salon,"10 000",5,2\n',
    )

    assert result['imported'] == 3
    rows = (
        await async_session.execute(
            select(PlanMetric).where(
                PlanMetric.period_start == date(2025, 1, 1),
                PlanMetric.period_end == date(2025, 1, 31),
                PlanMetric.company_id == 1,
            )
        )
    ).scalars().all()
    values = {row.metric_code: row.value for row in rows}
    assert values == {'revenue': 10000.0, 'clients': 5.0, 'wax_qty': 2.0}


@pytest.mark.asyncio
async def test_plan_sheet_csv_imports_google_thousands_commas(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon', group_id=1))
    await async_session.commit()

    result = await import_plan_sheet_csv(
        async_session,
        'month,company_id,Выручка,СЧ общий,Космо сумм.\n'
        '2025-01,1,"2,156,400","3,655","138,000"\n',
    )

    assert result['imported'] == 3
    rows = (
        await async_session.execute(
            select(PlanMetric).where(
                PlanMetric.period_start == date(2025, 1, 1),
                PlanMetric.period_end == date(2025, 1, 31),
                PlanMetric.company_id == 1,
            )
        )
    ).scalars().all()
    values = {row.metric_code: row.value for row in rows}
    assert values == {
        'revenue': 2156400.0,
        'avg_check_total': 3655.0,
        'cosmo_sum': 138000.0,
    }
