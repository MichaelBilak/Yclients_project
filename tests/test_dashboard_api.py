"""Dashboard JSON API (product portal metrics)."""

from datetime import date, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import api
from plan_import import import_plan_sheet_csv, import_services_sheet_csv, _normalize_google_sheet_csv_url
from api import app
from models import (
    Appointment,
    Client,
    Company,
    FinancialTransaction,
    GoodTransaction,
    Group,
    PlanMetric,
    Service,
    ServiceLabel,
    Staff,
    Transaction,
)


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
        assert 'extra_services' in body['data']
        assert 'plan_fact' not in body['data']

    app.dependency_overrides.clear()
    monkeypatch.setattr(api, 'API_KEY', '')


@pytest.mark.asyncio
async def test_dashboard_summary_revenue_and_change(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon', group_id=1))
    async_session.add(Staff(id=1, name='Master', position='Барбер', company_id=1))
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
        Transaction(id=1, appointment_id=1, service_id=10, service_title='Cut', cost=1200.0, first_cost=1500.0, amount=1, company_id=1),
        Transaction(id=2, appointment_id=2, service_id=10, service_title='Cut', cost=700.0, first_cost=900.0, amount=1, company_id=1),
        FinancialTransaction(id=1, date=datetime(2025, 1, 10, 12, 0, 0), amount=1000.0, record_id=1, visit_id=1, sold_item_id=10, sold_item_type='service', company_id=1),
        FinancialTransaction(id=2, date=datetime(2024, 12, 20, 12, 0, 0), amount=500.0, record_id=2, visit_id=2, sold_item_id=10, sold_item_type='service', company_id=1),
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
async def test_dashboard_summary_split_revenue_and_average_checks(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon', group_id=1))
    async_session.add(Staff(id=1, name='Master', position='Барбер', company_id=1))
    async_session.add_all([
        Client(id=1, name='Client 1', company_id=1, visits_count=1, last_visit_date=date(2025, 1, 10)),
        Client(id=2, name='Client 2', company_id=1, visits_count=1, last_visit_date=date(2025, 1, 11)),
        Service(id=10, title='Стрижка', company_id=1),
        Service(id=11, title='Воск', company_id=1),
    ])
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
            client_id=2,
            date=date(2025, 1, 11),
            datetime=datetime(2025, 1, 11, 12, 0, 0),
            create_date=datetime(2025, 1, 10, 12, 0, 0),
            seance_length=3600,
            attendance=1,
        ),
        Appointment(
            id=3,
            company_id=1,
            staff_id=1,
            client_id=1,
            date=date(2025, 1, 12),
            datetime=datetime(2025, 1, 12, 12, 0, 0),
            create_date=datetime(2025, 1, 11, 12, 0, 0),
            seance_length=3600,
            attendance=1,
        ),
    ])
    await async_session.flush()
    async_session.add_all([
        Transaction(id=1, appointment_id=1, service_id=10, service_title='Стрижка', cost=1000.0, first_cost=1000.0, amount=1, company_id=1),
        Transaction(id=2, appointment_id=1, service_id=11, service_title='Воск', cost=500.0, first_cost=500.0, amount=1, company_id=1),
        Transaction(id=3, appointment_id=2, service_id=10, service_title='Стрижка', cost=1500.0, first_cost=1500.0, amount=1, company_id=1),
        Transaction(id=4, appointment_id=1, service_id=11, service_title='Воск', cost=700.0, first_cost=700.0, amount=1, company_id=1),
        FinancialTransaction(id=1, date=datetime(2025, 1, 10, 12, 0, 0), amount=1000.0, record_id=1, visit_id=1, sold_item_id=10, sold_item_type='service', master_id=1, company_id=1),
        FinancialTransaction(id=2, date=datetime(2025, 1, 10, 12, 0, 0), amount=500.0, record_id=1, visit_id=1, sold_item_id=11, sold_item_type='service', master_id=1, company_id=1),
        FinancialTransaction(id=3, date=datetime(2025, 1, 11, 12, 0, 0), amount=1500.0, record_id=2, visit_id=2, sold_item_id=10, sold_item_type='service', master_id=1, company_id=1),
        FinancialTransaction(id=4, date=datetime(2025, 1, 10, 12, 0, 0), amount=700.0, record_id=1, visit_id=1, sold_item_id=11, sold_item_type='service', master_id=1, company_id=1),
        FinancialTransaction(id=5, date=datetime(2025, 1, 11, 12, 0, 0), amount=600.0, record_id=2, visit_id=2, sold_item_id=1, sold_item_type='goods_transaction', master_id=1, company_id=1),
        GoodTransaction(
            id=1,
            document_id=1,
            type_id=1,
            amount=1.0,
            cost=600.0,
            master_id=1,
            company_id=1,
            date=datetime(2025, 1, 11, 12, 0, 0),
        ),
        ServiceLabel(
            service_id=11,
            company_id=1,
            is_extra=True,
            source='google_sheet:services',
            updated_at=datetime(2025, 1, 1, 0, 0, 0),
        ),
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
    assert data['revenue']['total'] == 4300.0
    assert data['revenue']['service_revenue'] == 3700.0
    assert data['revenue']['goods_revenue'] == 600.0
    assert data['revenue']['extra_service_revenue'] == 1200.0
    assert data['revenue']['appointments'] == 3
    assert data['revenue']['service_count'] == 4.0
    assert data['revenue']['goods_count'] == 1.0
    assert data['revenue']['extra_service_count'] == 2.0
    assert data['revenue']['extra_service_appointments'] == 1
    assert data['revenue']['unique_clients'] == 2
    assert data['revenue']['extra_service_clients'] == 1
    assert data['average_check']['total'] == pytest.approx(1433.3333333333333)
    assert data['average_check']['services'] == pytest.approx(1233.3333333333333)
    assert data['average_check']['goods'] == 600.0
    assert data['average_check']['extra_services'] == 600.0
    assert data['visit_metrics']['extra_services_per_appointment_pct'] == pytest.approx(66.66666666666666)
    assert data['visit_metrics']['unique_clients'] == 2
    assert data['visit_metrics']['visits_per_client'] == 1.5
    assert data['visit_metrics']['extra_service_clients'] == 1
    assert data['visit_metrics']['extra_service_clients_pct'] == 50.0


@pytest.mark.asyncio
async def test_dashboard_top_services_merges_same_service_name_across_branches(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon 1', group_id=1))
    async_session.add(Company(id=2, title='Salon 2', group_id=1))
    async_session.add(Staff(id=1, name='Master 1', position='Барбер', company_id=1))
    async_session.add(Staff(id=2, name='Master 2', position='Барбер', company_id=2))
    async_session.add(Client(id=1, name='Client 1', company_id=1, visits_count=1, last_visit_date=date(2025, 1, 10)))
    async_session.add(Client(id=2, name='Client 2', company_id=2, visits_count=1, last_visit_date=date(2025, 1, 11)))
    async_session.add_all([
        Service(id=10, title='Black Mask', company_id=1),
        Service(id=20, title='Black Mask', company_id=2),
        Service(id=30, title='Комплексное мытьё головы', company_id=1),
        Service(id=40, title='Комплексное мытье головы', company_id=2),
        Service(id=50, title='Стрижка', company_id=1),
    ])
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
            company_id=2,
            staff_id=2,
            client_id=2,
            date=date(2025, 1, 11),
            datetime=datetime(2025, 1, 11, 12, 0, 0),
            create_date=datetime(2025, 1, 10, 12, 0, 0),
            seance_length=3600,
            attendance=1,
        ),
    ])
    await async_session.flush()
    async_session.add_all([
        Transaction(id=1, appointment_id=1, service_id=10, service_title='Black Mask', cost=100.0, first_cost=100.0, amount=1, company_id=1),
        Transaction(id=2, appointment_id=2, service_id=20, service_title='Black Mask', cost=200.0, first_cost=200.0, amount=2, company_id=2),
        Transaction(id=3, appointment_id=1, service_id=30, service_title='Комплексное мытьё головы', cost=50.0, first_cost=50.0, amount=1, company_id=1),
        Transaction(id=4, appointment_id=2, service_id=40, service_title='Комплексное мытье головы', cost=75.0, first_cost=75.0, amount=1, company_id=2),
        Transaction(id=5, appointment_id=1, service_id=50, service_title='Стрижка', cost=80.0, first_cost=80.0, amount=1, company_id=1),
        FinancialTransaction(id=1, date=datetime(2025, 1, 10, 12, 0, 0), amount=100.0, record_id=1, visit_id=1, sold_item_id=10, sold_item_type='service', master_id=1, company_id=1),
        FinancialTransaction(id=2, date=datetime(2025, 1, 11, 12, 0, 0), amount=400.0, record_id=2, visit_id=2, sold_item_id=20, sold_item_type='service', master_id=2, company_id=2),
        FinancialTransaction(id=3, date=datetime(2025, 1, 10, 12, 0, 0), amount=50.0, record_id=1, visit_id=1, sold_item_id=30, sold_item_type='service', master_id=1, company_id=1),
        FinancialTransaction(id=4, date=datetime(2025, 1, 11, 12, 0, 0), amount=75.0, record_id=2, visit_id=2, sold_item_id=40, sold_item_type='service', master_id=2, company_id=2),
        FinancialTransaction(id=5, date=datetime(2025, 1, 10, 12, 0, 0), amount=80.0, record_id=1, visit_id=1, sold_item_id=50, sold_item_type='service', master_id=1, company_id=1),
        ServiceLabel(service_id=10, company_id=1, is_extra=True, source='google_sheet:services', updated_at=datetime(2025, 1, 1, 0, 0, 0)),
        ServiceLabel(service_id=20, company_id=2, is_extra=True, source='google_sheet:services', updated_at=datetime(2025, 1, 1, 0, 0, 0)),
    ])
    await async_session.commit()

    async def override_db():
        yield async_session

    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        r = await client.get(
            '/dashboard/widget/top_services',
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31'},
        )
        r_extra = await client.get(
            '/dashboard/widget/extra_services',
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31'},
        )
    app.dependency_overrides.clear()

    assert r.status_code == 200
    rows = r.json()['data']
    assert len(rows) == 3

    black_mask = next(row for row in rows if row['title'] == 'Black Mask')
    assert black_mask['sold'] == 3
    assert black_mask['revenue'] == 500.0
    assert black_mask['service_count'] == 2
    assert black_mask['branch_count'] == 2

    wash = next(row for row in rows if row['title'].replace('ё', 'е') == 'Комплексное мытье головы')
    assert wash['sold'] == 2
    assert wash['revenue'] == 125.0
    assert wash['service_count'] == 2
    assert wash['branch_count'] == 2

    assert r_extra.status_code == 200
    extra_rows = r_extra.json()['data']
    assert len(extra_rows) == 1
    assert extra_rows[0]['title'] == 'Black Mask'
    assert extra_rows[0]['sold'] == 3
    assert extra_rows[0]['revenue'] == 500.0
    assert extra_rows[0]['service_count'] == 2
    assert extra_rows[0]['branch_count'] == 2


@pytest.mark.asyncio
async def test_extra_service_labels_are_scoped_to_branch_in_calculations(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon 1', group_id=1))
    async_session.add(Company(id=2, title='Salon 2', group_id=1))
    async_session.add(Staff(id=1, name='Master 1', position='Барбер', company_id=1))
    async_session.add(Staff(id=2, name='Master 2', position='Барбер', company_id=2))
    async_session.add(Client(id=1, name='Client 1', company_id=1, visits_count=1, last_visit_date=date(2025, 1, 10)))
    async_session.add(Client(id=2, name='Client 2', company_id=2, visits_count=1, last_visit_date=date(2025, 1, 11)))
    async_session.add(Service(id=10, title='Branch-only extra', category_title='Уход', company_id=1))
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
            company_id=2,
            staff_id=2,
            client_id=2,
            date=date(2025, 1, 11),
            datetime=datetime(2025, 1, 11, 12, 0, 0),
            create_date=datetime(2025, 1, 10, 12, 0, 0),
            seance_length=3600,
            attendance=1,
        ),
    ])
    await async_session.flush()
    async_session.add_all([
        Transaction(id=1, appointment_id=1, service_id=10, service_title='Branch-only extra', cost=100.0, first_cost=100.0, amount=1, company_id=1),
        Transaction(id=2, appointment_id=2, service_id=10, service_title='Branch-only extra', cost=200.0, first_cost=200.0, amount=1, company_id=2),
        FinancialTransaction(id=1, date=datetime(2025, 1, 10, 12, 0, 0), amount=100.0, record_id=1, visit_id=1, sold_item_id=10, sold_item_type='service', master_id=1, company_id=1),
        FinancialTransaction(id=2, date=datetime(2025, 1, 11, 12, 0, 0), amount=200.0, record_id=2, visit_id=2, sold_item_id=10, sold_item_type='service', master_id=2, company_id=2),
        ServiceLabel(service_id=10, company_id=1, is_extra=True, source='google_sheet:services', updated_at=datetime(2025, 1, 1, 0, 0, 0)),
    ])
    await async_session.commit()

    async def override_db():
        yield async_session

    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        all_summary = await client.get(
            '/dashboard/widget/summary',
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31'},
        )
        branch_summary = await client.get(
            '/dashboard/widget/summary',
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31', 'company_id': 1},
        )
        other_branch_summary = await client.get(
            '/dashboard/widget/summary',
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31', 'company_id': 2},
        )
        extra_services = await client.get(
            '/dashboard/widget/extra_services',
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31'},
        )
    app.dependency_overrides.clear()

    all_data = all_summary.json()['data']
    branch_data = branch_summary.json()['data']
    other_branch_data = other_branch_summary.json()['data']

    assert all_summary.status_code == 200
    assert branch_summary.status_code == 200
    assert other_branch_summary.status_code == 200
    assert all_data['revenue']['service_revenue'] == 300.0
    assert all_data['revenue']['extra_service_revenue'] == 100.0
    assert all_data['revenue']['extra_service_count'] == 1.0
    assert branch_data['revenue']['extra_service_revenue'] == 100.0
    assert branch_data['revenue']['extra_service_count'] == 1.0
    assert other_branch_data['revenue']['extra_service_revenue'] == 0.0
    assert other_branch_data['revenue']['extra_service_count'] == 0.0

    assert extra_services.status_code == 200
    extra_rows = extra_services.json()['data']
    assert len(extra_rows) == 1
    assert extra_rows[0]['sold'] == 1
    assert extra_rows[0]['revenue'] == 100.0
    assert extra_rows[0]['branch_count'] == 1


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
async def test_dashboard_staff_directory_csv_exports_working_staff(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon 1', group_id=1))
    async_session.add(Company(id=2, title='Salon 2', group_id=1))
    async_session.add(Staff(id=10, name='Active', position='Барбер', company_id=1, fired=0, bookable=True))
    async_session.add(Staff(id=20, name='Fired', position='Барбер', company_id=1, fired=1, bookable=False))
    async_session.add(Staff(id=30, name='Admin', position='Администратор', company_id=2, fired=0, user_id=500))
    async_session.add(Staff(id=40, name='Администратор Ривьера', position='Администратор', company_id=2, fired=0))
    await async_session.commit()

    async def override_db():
        yield async_session

    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        active_only = await client.get('/dashboard/staff_directory.csv')
        all_staff = await client.get('/dashboard/staff_directory.csv', params={'include_fired': 1})
    app.dependency_overrides.clear()

    assert active_only.status_code == 200
    assert active_only.headers['content-type'].startswith('text/csv')
    assert 'company_id,company_title,staff_id,staff_name,position,user_id,fired,working,bookable' in active_only.text
    assert '1,Salon 1,10,Active' in active_only.text
    assert '20,Fired' not in active_only.text
    assert '2,Salon 2,30,Admin' in active_only.text
    assert 'Администратор Ривьера' not in active_only.text

    assert all_staff.status_code == 200
    assert '1,Salon 1,20,Fired' in all_staff.text
    assert 'Администратор Ривьера' not in all_staff.text


@pytest.mark.asyncio
async def test_dashboard_staff_filter_excludes_waitlist_and_fired_staff(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon 1', group_id=1))
    async_session.add(Company(id=2, title='Salon 2', group_id=1))
    async_session.add(Staff(id=10, name='Active', position='Барбер', company_id=1, fired=0))
    async_session.add(Staff(id=20, name='Fired', position='Барбер', company_id=1, fired=1))
    async_session.add(Staff(id=30, name='Лист ожидания', position='Системный', company_id=1, fired=0))
    async_session.add(Staff(id=40, name='Admin', position='Администратор', company_id=2, fired=0))
    async_session.add(Staff(id=50, name='Администратор Ривьера', position='Администратор', company_id=2, fired=0))
    await async_session.commit()

    async def override_db():
        yield async_session

    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        all_staff = await client.get('/dashboard/staff')
        branch_staff = await client.get('/dashboard/staff', params={'company_id': 1})
    app.dependency_overrides.clear()

    assert all_staff.status_code == 200
    assert [row['name'] for row in all_staff.json()['data']] == ['Active', 'Admin']
    assert branch_staff.status_code == 200
    assert [row['name'] for row in branch_staff.json()['data']] == ['Active']


@pytest.mark.asyncio
async def test_dashboard_bundle_filters_by_staff(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon', group_id=1))
    async_session.add(Staff(id=1, name='Master 1', position='Барбер', company_id=1))
    async_session.add(Staff(id=2, name='Master 2', position='Барбер', company_id=1))
    async_session.add(Client(id=1, name='Client 1', company_id=1))
    async_session.add(Client(id=2, name='Client 2', company_id=1))
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
            staff_id=2,
            client_id=2,
            date=date(2025, 1, 10),
            datetime=datetime(2025, 1, 10, 14, 0, 0),
            create_date=datetime(2025, 1, 9, 14, 0, 0),
            seance_length=3600,
            attendance=1,
        ),
    ])
    await async_session.flush()
    async_session.add_all([
        Transaction(id=1, appointment_id=1, service_id=10, service_title='Cut 1', cost=1000.0, first_cost=1000.0, amount=1, company_id=1),
        Transaction(id=2, appointment_id=2, service_id=20, service_title='Cut 2', cost=2000.0, first_cost=2000.0, amount=1, company_id=1),
        FinancialTransaction(id=1, date=datetime(2025, 1, 10, 12, 0, 0), amount=1000.0, record_id=1, visit_id=1, sold_item_id=10, sold_item_type='service', master_id=1, company_id=1),
        FinancialTransaction(id=2, date=datetime(2025, 1, 10, 14, 0, 0), amount=2000.0, record_id=2, visit_id=2, sold_item_id=20, sold_item_type='service', master_id=2, company_id=1),
        FinancialTransaction(id=3, date=datetime(2025, 1, 10, 13, 0, 0), amount=300.0, record_id=1, visit_id=1, sold_item_id=1, sold_item_type='goods_transaction', master_id=1, company_id=1),
        FinancialTransaction(id=4, date=datetime(2025, 1, 10, 15, 0, 0), amount=700.0, record_id=2, visit_id=2, sold_item_id=2, sold_item_type='goods_transaction', master_id=2, company_id=1),
        GoodTransaction(
            id=1,
            document_id=1,
            type_id=1,
            amount=-1.0,
            cost=300.0,
            master_id=1,
            company_id=1,
            date=datetime(2025, 1, 10, 13, 0, 0),
        ),
        GoodTransaction(
            id=2,
            document_id=2,
            type_id=1,
            amount=-1.0,
            cost=700.0,
            master_id=2,
            company_id=1,
            date=datetime(2025, 1, 10, 15, 0, 0),
        ),
    ])
    await async_session.commit()

    async def override_db():
        yield async_session

    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        r = await client.get(
            '/dashboard/bundle',
            params={
                'start_date': '2025-01-01',
                'end_date': '2025-01-31',
                'staff_id': 1,
            },
        )
    app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()['data']
    assert data['summary']['revenue']['total'] == 1300.0
    assert data['summary']['revenue']['appointments'] == 1
    assert data['revenue_daily'] == [
        {
            'date': '2025-01-10',
            'revenue': 1300.0,
            'service_revenue': 1000.0,
            'goods_revenue': 300.0,
            'appointments': 1,
        }
    ]
    assert [row['title'] for row in data['top_services']] == ['Cut 1']


@pytest.mark.asyncio
async def test_dashboard_plan_fact_uses_plan_and_fact_formulas(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon', group_id=1))
    async_session.add(Staff(id=1, name='Master', position='Барбер', company_id=1))
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
        Appointment(
            id=3,
            company_id=1,
            staff_id=1,
            client_id=1,
            date=date(2025, 1, 12),
            datetime=datetime(2025, 1, 12, 12, 0, 0),
            create_date=datetime(2025, 1, 11, 12, 0, 0),
            seance_length=3600,
            attendance=1,
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
        Transaction(
            id=3,
            appointment_id=3,
            service_id=12,
            service_title='стрижка',
            cost=500.0,
            first_cost=500.0,
            amount=1,
            company_id=1,
        ),
        FinancialTransaction(
            id=1,
            date=datetime(2025, 1, 10, 12, 0, 0),
            amount=1000.0,
            record_id=1,
            visit_id=1,
            sold_item_id=10,
            sold_item_type='service',
            master_id=1,
            company_id=1,
        ),
        FinancialTransaction(
            id=2,
            date=datetime(2025, 1, 10, 12, 0, 0),
            amount=1000.0,
            record_id=1,
            visit_id=1,
            sold_item_id=11,
            sold_item_type='service',
            master_id=1,
            company_id=1,
        ),
        FinancialTransaction(
            id=3,
            date=datetime(2025, 1, 12, 12, 0, 0),
            amount=500.0,
            record_id=3,
            visit_id=3,
            sold_item_id=12,
            sold_item_type='service',
            master_id=1,
            company_id=1,
        ),
        FinancialTransaction(
            id=4,
            date=datetime(2025, 1, 11, 12, 0, 0),
            amount=1500.0,
            record_id=1,
            visit_id=1,
            sold_item_id=1,
            sold_item_type='goods_transaction',
            master_id=1,
            company_id=1,
        ),
        GoodTransaction(
            id=1,
            document_id=1,
            type_id=1,
            amount=-3.0,
            cost=1500.0,
            master_id=1,
            company_id=1,
            date=datetime(2025, 1, 11, 12, 0, 0),
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
        async_session.add(
            PlanMetric(
                period_start=date(2025, 1, 1),
                period_end=date(2025, 1, 31),
                company_id=1,
                staff_id=1,
                staff_category='barber',
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
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31'},
        )
        r_staff = await client.get(
            '/dashboard/widget/plan_fact',
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31', 'company_id': 1},
        )
        r_selected_staff = await client.get(
            '/dashboard/widget/plan_fact',
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31', 'staff_id': 1},
        )
        r_partial = await client.get(
            '/dashboard/widget/plan_fact',
            params={'start_date': '2025-01-15', 'end_date': '2025-01-20'},
        )
        r_summary = await client.get(
            '/dashboard/widget/summary',
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31'},
        )
    app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()['data']
    assert data['plan_period'] == {'start': '2025-01-01', 'end': '2025-01-31'}
    assert data['view_scope'] == 'branch'
    assert data['groups'][0]['title'] == 'Сеть'
    branch_group = next(group for group in data['groups'] if group['scope'] == 'branch')
    assert branch_group['title'] == 'Salon'

    cells = {cell['code']: cell for cell in branch_group['metrics']}
    assert cells['revenue']['fact'] == 4000.0
    assert cells['revenue']['completion_pct'] == pytest.approx(57.14, abs=0.01)
    assert cells['avg_check_total']['fact'] == 2000.0
    assert cells['clients']['fact'] == 2.0
    assert cells['wax_qty']['fact'] == 1.0
    assert cells['camouflage_qty']['fact'] == 2.0
    assert cells['cosmo_qty']['fact'] == 3.0
    assert cells['cosmo_sum']['fact'] == 1500.0
    assert 'reviews_qty' not in cells
    assert cells['opz_qty']['fact'] == 1.0
    assert cells['opz_pct']['fact'] == 50.0
    assert cells['extra_services_pct']['fact'] == 150.0
    summary_avg = r_summary.json()['data']['average_check']['total']
    assert cells['avg_check_total']['fact'] == summary_avg

    assert r_staff.status_code == 200
    staff_data = r_staff.json()['data']
    assert staff_data['view_scope'] == 'staff'
    assert staff_data['parent_group']['title'] == 'Salon'
    assert staff_data['groups'][0]['title'] == 'Master'
    assert staff_data['groups'][0]['category'] == 'barber'
    staff_cells = {cell['code']: cell for cell in staff_data['groups'][0]['metrics']}
    assert staff_cells['revenue']['plan'] == 7000.0
    assert staff_cells['revenue']['fact'] == 4000.0

    assert r_selected_staff.status_code == 200
    selected_staff_data = r_selected_staff.json()['data']
    assert selected_staff_data['view_scope'] == 'staff'
    assert selected_staff_data['branch']['title'] == 'Salon'
    assert selected_staff_data['selected_staff']['name'] == 'Master'
    assert [group['title'] for group in selected_staff_data['groups']] == ['Master']

    assert r_partial.status_code == 200
    partial_data = r_partial.json()['data']
    assert partial_data['period'] == {'start': '2025-01-15', 'end': '2025-01-20'}
    assert partial_data['plan_period'] == {'start': '2025-01-01', 'end': '2025-01-31'}
    partial_branch_group = next(group for group in partial_data['groups'] if group['scope'] == 'branch')
    partial_cells = {cell['code']: cell for cell in partial_branch_group['metrics']}
    assert partial_cells['revenue']['plan'] == 7000.0
    assert partial_cells['revenue']['fact'] == 0.0


@pytest.mark.asyncio
async def test_dashboard_plan_fact_lists_staff_plans_for_each_branch(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon 1', group_id=1))
    async_session.add(Company(id=2, title='Salon 2', group_id=1))
    async_session.add(Staff(id=1, name='Master 1', position='Барбер', company_id=1, fired=0))
    async_session.add(Staff(id=2, name='Admin 2', position='Администратор', company_id=2, fired=0, user_id=500))
    async_session.add(Staff(id=3, name='No Plan', position='Барбер', company_id=2, fired=0))
    now = datetime(2025, 1, 1, 0, 0, 0)
    async_session.add_all([
        PlanMetric(
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            company_id=1,
            staff_id=1,
            staff_category='barber',
            metric_code='revenue',
            value=1000.0,
            updated_at=now,
        ),
        PlanMetric(
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            company_id=2,
            staff_id=2,
            staff_category='administrator',
            metric_code='revenue',
            value=2000.0,
            updated_at=now,
        ),
    ])
    await async_session.commit()

    async def override_db():
        yield async_session

    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        r = await client.get(
            '/dashboard/widget/plan_fact',
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31'},
        )
    app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()['data']
    assert data['view_scope'] == 'branch'
    assert [section['branch']['title'] for section in data['branch_sections']] == ['Salon 1', 'Salon 2']

    groups_by_branch = {
        section['branch']['title']: section['groups']
        for section in data['branch_sections']
    }
    assert [group['title'] for group in groups_by_branch['Salon 1']] == ['Master 1']
    assert groups_by_branch['Salon 1'][0]['category'] == 'barber'
    assert [group['title'] for group in groups_by_branch['Salon 2']] == ['Admin 2']
    assert groups_by_branch['Salon 2'][0]['category'] == 'administrator'


@pytest.mark.asyncio
async def test_admin_opz_attributes_to_creator(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon', group_id=1))
    async_session.add(Staff(id=1, name='Barber', position='Барбер', company_id=1))
    async_session.add(Staff(id=2, name='Admin', position='Администратор', company_id=1, user_id=500))
    async_session.add(Client(id=1, name='C', company_id=1, visits_count=1, last_visit_date=date(2025, 1, 10)))
    now = datetime(2025, 1, 1)
    await async_session.flush()

    async_session.add_all([
        Appointment(
            id=1, company_id=1, staff_id=1, client_id=1,
            date=date(2025, 1, 10),
            datetime=datetime(2025, 1, 10, 12, 0, 0),
            create_date=datetime(2025, 1, 9, 12, 0, 0),
            seance_length=3600, attendance=1, created_user_id=999,
        ),
        Appointment(
            id=2, company_id=1, staff_id=1, client_id=1,
            date=date(2025, 2, 10),
            datetime=datetime(2025, 2, 10, 12, 0, 0),
            create_date=datetime(2025, 1, 10, 18, 0, 0),
            seance_length=3600, attendance=0, created_user_id=500,
        ),
        PlanMetric(
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            company_id=1,
            staff_id=1,
            staff_category='barber',
            metric_code='opz_qty',
            value=1.0,
            updated_at=now,
        ),
        PlanMetric(
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            company_id=1,
            staff_id=2,
            staff_category='administrator',
            metric_code='opz_qty',
            value=1.0,
            updated_at=now,
        ),
    ])
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
    app.dependency_overrides.clear()

    assert r.status_code == 200
    groups = r.json()['data']['groups']
    admin_group = next(g for g in groups if g['category'] == 'administrator')
    barber_group = next(g for g in groups if g['category'] == 'barber')
    admin_cells = {cell['code']: cell for cell in admin_group['metrics']}
    barber_cells = {cell['code']: cell for cell in barber_group['metrics']}
    assert admin_cells['opz_qty']['fact'] == 1.0
    assert barber_cells['opz_qty']['fact'] == 1.0


@pytest.mark.asyncio
async def test_plan_fact_excludes_fired_staff(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon', group_id=1))
    async_session.add(Staff(id=1, name='Active', position='Барбер', company_id=1, fired=0))
    async_session.add(Staff(id=2, name='Fired', position='Барбер', company_id=1, fired=1))
    async_session.add(Staff(id=3, name='лист ожидания', position='Барбер', company_id=1, fired=0))
    async_session.add(Staff(id=4, name='No Plan', position='Барбер', company_id=1, fired=0))
    async_session.add(Staff(id=5, name='Zero Plan', position='Барбер', company_id=1, fired=0))
    now = datetime(2025, 1, 1)
    async_session.add_all([
        PlanMetric(
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            company_id=1,
            staff_id=1,
            staff_category='barber',
            metric_code='revenue',
            value=1000.0,
            updated_at=now,
        ),
        PlanMetric(
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            company_id=1,
            staff_id=5,
            staff_category='barber',
            metric_code='revenue',
            value=0.0,
            updated_at=now,
        ),
    ])
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
    app.dependency_overrides.clear()

    assert r.status_code == 200
    groups = r.json()['data']['groups']
    assert [group['title'] for group in groups] == ['Active']


@pytest.mark.asyncio
async def test_opz_period_uses_future_appointment_create_date(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon', group_id=1))
    async_session.add(Staff(id=1, name='Barber', position='Барбер', company_id=1))
    async_session.add_all([
        Client(id=1, name='Dec Visit', company_id=1, visits_count=1, last_visit_date=date(2024, 12, 31)),
        Client(id=2, name='Jan Visit', company_id=1, visits_count=1, last_visit_date=date(2025, 1, 31)),
        Client(id=3, name='Late Booking', company_id=1, visits_count=1, last_visit_date=date(2025, 1, 1)),
    ])
    await async_session.flush()

    async_session.add_all([
        Appointment(
            id=1,
            company_id=1,
            staff_id=1,
            client_id=1,
            date=date(2024, 12, 31),
            datetime=datetime(2024, 12, 31, 12, 0, 0),
            create_date=datetime(2024, 12, 1, 12, 0, 0),
            seance_length=3600,
            attendance=1,
        ),
        Appointment(
            id=2,
            company_id=1,
            staff_id=1,
            client_id=1,
            date=date(2025, 1, 20),
            datetime=datetime(2025, 1, 20, 12, 0, 0),
            create_date=datetime(2025, 1, 1, 10, 0, 0),
            seance_length=3600,
            attendance=0,
        ),
        Appointment(
            id=3,
            company_id=1,
            staff_id=1,
            client_id=2,
            date=date(2025, 1, 31),
            datetime=datetime(2025, 1, 31, 12, 0, 0),
            create_date=datetime(2025, 1, 1, 12, 0, 0),
            seance_length=3600,
            attendance=1,
        ),
        Appointment(
            id=4,
            company_id=1,
            staff_id=1,
            client_id=2,
            date=date(2025, 2, 20),
            datetime=datetime(2025, 2, 20, 12, 0, 0),
            create_date=datetime(2025, 2, 1, 10, 0, 0),
            seance_length=3600,
            attendance=0,
        ),
        Appointment(
            id=5,
            company_id=1,
            staff_id=1,
            client_id=3,
            date=date(2025, 1, 1),
            datetime=datetime(2025, 1, 1, 12, 0, 0),
            create_date=datetime(2024, 12, 1, 12, 0, 0),
            seance_length=3600,
            attendance=1,
        ),
        Appointment(
            id=6,
            company_id=1,
            staff_id=1,
            client_id=3,
            date=date(2025, 1, 20),
            datetime=datetime(2025, 1, 20, 12, 0, 0),
            create_date=datetime(2025, 1, 3, 10, 0, 0),
            seance_length=3600,
            attendance=0,
        ),
    ])
    await async_session.commit()

    async def override_db():
        yield async_session

    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        jan = await client.get(
            '/dashboard/widget/plan_fact',
            params={'start_date': '2025-01-01', 'end_date': '2025-01-31'},
        )
        feb = await client.get(
            '/dashboard/widget/plan_fact',
            params={'start_date': '2025-02-01', 'end_date': '2025-02-28'},
        )
    app.dependency_overrides.clear()

    assert jan.status_code == 200
    assert feb.status_code == 200

    jan_branch = next(group for group in jan.json()['data']['groups'] if group['scope'] == 'branch')
    feb_branch = next(group for group in feb.json()['data']['groups'] if group['scope'] == 'branch')
    jan_cells = {cell['code']: cell for cell in jan_branch['metrics']}
    feb_cells = {cell['code']: cell for cell in feb_branch['metrics']}
    assert jan_cells['opz_qty']['fact'] == 1.0
    assert feb_cells['opz_qty']['fact'] == 1.0


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
async def test_services_sheet_csv_imports_extra_service_labels(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Group(id=2, title='G2'))
    async_session.add(Company(id=1, title='Salon', group_id=1))
    async_session.add(Company(id=2, title='Salon 2', group_id=2))
    async_session.add(Service(id=10, title='Стрижка', company_id=1))
    async_session.add(Service(id=11, title='Воск', company_id=1))
    async_session.add(Service(id=12, title='Воск', company_id=2))
    await async_session.commit()

    result = await import_services_sheet_csv(
        async_session,
        'company_id,service_id,service_title,доп услуга\n'
        '1,10,Стрижка,нет\n'
        ',,Воск,да\n',
    )

    assert result['imported'] == 2
    assert result['processed'] == 2
    rows = (await async_session.execute(select(ServiceLabel))).scalars().all()
    assert sorted((row.service_id, row.company_id, row.is_extra) for row in rows) == [
        (11, 1, True),
        (12, 2, True),
    ]


def test_google_sheet_page_url_is_normalized_to_csv_export():
    url = 'https://docs.google.com/spreadsheets/d/sheet-id/edit#gid=12345'

    assert _normalize_google_sheet_csv_url(url) == (
        'https://docs.google.com/spreadsheets/d/sheet-id/export?format=csv&gid=12345'
    )


@pytest.mark.asyncio
async def test_services_sheet_csv_imports_current_format_with_category_scope(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Group(id=2, title='G2'))
    async_session.add(Company(id=1, title='Salon 1', group_id=1))
    async_session.add(Company(id=2, title='Salon 2', group_id=2))
    async_session.add(Service(id=10, title='Black Mask', category_title='Уход', company_id=1))
    async_session.add(Service(id=11, title='Black Mask', category_title='Основные', company_id=2))
    async_session.add(Service(id=12, title='Окантовка', category_title='Финиш', company_id=2))
    await async_session.commit()

    result = await import_services_sheet_csv(
        async_session,
        'Категория,id_услуги,Название услуги,доп услуга\n'
        'Уход,,Black Mask,да\n'
        'Финиш,12,Окантовка,да\n',
    )

    assert result['imported'] == 2
    assert result['processed'] == 2
    rows = (await async_session.execute(select(ServiceLabel))).scalars().all()
    assert sorted((row.service_id, row.company_id, row.is_extra) for row in rows) == [
        (10, 1, True),
        (12, 2, True),
    ]


@pytest.mark.asyncio
async def test_services_sheet_csv_category_falls_back_when_service_categories_are_empty(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon 1', group_id=1))
    async_session.add(Service(id=10, title='Black Mask', category_title='', company_id=1))
    await async_session.commit()

    result = await import_services_sheet_csv(
        async_session,
        'Категория,id_услуги,Название услуги,доп услуга\n'
        'Уход,,Black Mask,да\n',
    )

    assert result['imported'] == 1
    assert result['processed'] == 1
    rows = (await async_session.execute(select(ServiceLabel))).scalars().all()
    assert [(row.service_id, row.company_id, row.is_extra) for row in rows] == [
        (10, 1, True),
    ]


@pytest.mark.asyncio
async def test_plan_sheet_csv_imports_staff_rows_and_validates_branch_totals(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon', group_id=1))
    async_session.add(Staff(id=10, name='Alice', position='Барбер', company_id=1))
    await async_session.commit()

    result = await import_plan_sheet_csv(
        async_session,
        'month,branch,staff_id,category,выручка,кол-во клиентов,воск\n'
        '2025-01,Salon,,,10000,5,2\n'
        '2025-01,,10,Барбер,8000,4,2\n',
    )

    assert result['imported'] == 6
    assert any('branch staff total' in warning for warning in result['warnings'])
    rows = (
        await async_session.execute(
            select(PlanMetric).where(
                PlanMetric.period_start == date(2025, 1, 1),
                PlanMetric.period_end == date(2025, 1, 31),
                PlanMetric.company_id == 1,
                PlanMetric.staff_id == 10,
            )
        )
    ).scalars().all()
    values = {row.metric_code: row.value for row in rows}
    assert values == {'revenue': 8000.0, 'clients': 4.0, 'wax_qty': 2.0}
    assert {row.staff_category for row in rows} == {'barber'}


@pytest.mark.asyncio
async def test_plan_sheet_csv_imports_flat_staff_rows_and_derives_branch_plan(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon', group_id=1))
    async_session.add(Staff(id=10, name='Alice', position='Барбер', company_id=1))
    async_session.add(Staff(id=20, name='Admin', position='Администратор', company_id=1))
    async_session.add(
        PlanMetric(
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            company_id=1,
            staff_id=10,
            staff_category='barber',
            metric_code='wax_qty',
            value=9.0,
            updated_at=datetime(2025, 1, 1),
        )
    )
    await async_session.commit()

    result = await import_plan_sheet_csv(
        async_session,
        'month,company_id,branch,stuff_id,stuff_name,position,Выручка,СЧ общий,Кол-во клиентов,"Воск, шт","Камуфляж, шт","Уход лицо, шт","Уход голова, шт","Космо, шт",Космо сумм.,"ОПЗ, шт"\n'
        '2025-01,1,Salon,10,Alice,Барбер,7000,,7,,2,,,,1000,1\n'
        '2025-01,1,Salon,20,Admin,Администратор,3000,,3,,,,,4,500,2\n',
    )

    assert result['imported'] == 16
    assert result['warnings'] == []

    rows = (
        await async_session.execute(
            select(PlanMetric).where(
                PlanMetric.period_start == date(2025, 1, 1),
                PlanMetric.period_end == date(2025, 1, 31),
                PlanMetric.company_id == 1,
            )
        )
    ).scalars().all()
    values = {
        (row.staff_id, row.metric_code): row.value
        for row in rows
    }
    assert values[(10, 'revenue')] == 7000.0
    assert values[(10, 'camouflage_qty')] == 2.0
    assert (10, 'wax_qty') not in values
    assert values[(20, 'revenue')] == 3000.0
    assert values[(20, 'cosmo_sum')] == 500.0
    assert values[(None, 'revenue')] == 10000.0
    assert values[(None, 'clients')] == 10.0
    assert values[(None, 'cosmo_sum')] == 1500.0


@pytest.mark.asyncio
async def test_plan_sheet_csv_skips_metrics_not_applicable_to_administrators(async_session):
    async_session.add(Group(id=1, title='G1'))
    async_session.add(Company(id=1, title='Salon', group_id=1))
    async_session.add(Staff(id=20, name='Admin', position='Администратор', company_id=1))
    await async_session.commit()

    result = await import_plan_sheet_csv(
        async_session,
        'month,branch,staff_id,выручка,воск,космо сумм.\n'
        '2025-01,Salon,20,1000,3,500\n',
    )

    assert result['imported'] == 4
    assert any('skipped metrics not applicable to administrator' in warning for warning in result['warnings'])
    rows = (
        await async_session.execute(
            select(PlanMetric).where(
                PlanMetric.period_start == date(2025, 1, 1),
                PlanMetric.period_end == date(2025, 1, 31),
                PlanMetric.company_id == 1,
                PlanMetric.staff_id == 20,
            )
        )
    ).scalars().all()
    values = {row.metric_code: row.value for row in rows}
    assert values == {'revenue': 1000.0, 'cosmo_sum': 500.0}


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
