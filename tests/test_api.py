import pytest
from httpx import ASGITransport, AsyncClient

import api
from api import app
from models import Company, GoodTransaction, Group


@pytest.mark.asyncio
async def test_api_key_blocks_unauthorized_requests(async_session, monkeypatch):
    monkeypatch.setattr(api, 'API_KEY', 'secret123')

    async def override_db():
        yield async_session

    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        r1 = await client.get('/companies')
        assert r1.status_code == 401

        r2 = await client.get('/companies', headers={'X-API-Key': 'wrong'})
        assert r2.status_code == 401

        r3 = await client.get('/companies', headers={'X-API-Key': 'secret123'})
        assert r3.status_code == 200

        r4 = await client.get('/health')
        assert r4.status_code == 200

    app.dependency_overrides.clear()
    monkeypatch.setattr(api, 'API_KEY', '')


@pytest.mark.asyncio
async def test_companies_endpoint_applies_pagination(async_session):
    group = Group(id=1, title='Group')
    async_session.add(group)
    async_session.add_all([
        Company(id=1, title='A', group_id=1),
        Company(id=2, title='B', group_id=1),
        Company(id=3, title='C', group_id=1),
    ])
    await async_session.commit()

    async def override_db():
        yield async_session

    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        response = await client.get('/companies', params={'limit': 2, 'offset': 1})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload['total'] == 3
    assert payload['limit'] == 2
    assert payload['offset'] == 1
    assert [item['id'] for item in payload['data']] == [2, 3]


@pytest.mark.asyncio
async def test_sync_trigger_queues_job(async_session, monkeypatch):
    captured = {}

    class DummyJob:
        id = 42
        mode = 'incremental'
        initiator = 'dashboard'

    async def fake_enqueue(self, db, mode, initiator):
        captured['mode'] = mode
        captured['initiator'] = initiator
        return DummyJob()

    async def override_db():
        yield async_session

    monkeypatch.setattr(api.SyncJobService, 'async_enqueue_job', fake_enqueue)
    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        response = await client.post('/sync/trigger', json={'mode': 'incremental', 'initiator': 'dashboard'})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        'status': 'queued',
        'job_id': 42,
        'mode': 'incremental',
        'initiator': 'dashboard',
    }
    assert captured == {'mode': 'incremental', 'initiator': 'dashboard'}


@pytest.mark.asyncio
async def test_csv_export_streams_rows(async_session):
    async_session.add(GoodTransaction(id=1, company_id=7, type_id=1, amount=2.0, cost=10.0))
    async_session.add(GoodTransaction(id=2, company_id=7, type_id=3, amount=1.0, cost=5.0))
    await async_session.commit()

    async def override_db():
        yield async_session

    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        response = await client.get('/export/csv/goods_transactions')

    app.dependency_overrides.clear()

    assert response.status_code == 200
    content = response.text
    assert 'id,document_id,type_id,good_id,storage_id,amount,cost_per_unit,cost,discount,master_id,client_id,company_id' in content
    assert '1,,1,,,2.0,,10.0,,,,7' in content
    assert '2,,3,,,1.0,,5.0,,,,7' in content


@pytest.mark.asyncio
async def test_goods_transactions_endpoint_no_longer_depends_on_date_params(async_session):
    async_session.add(GoodTransaction(id=10, company_id=9, type_id=1, amount=1.0, cost=1.0))
    await async_session.commit()

    async def override_db():
        yield async_session

    app.dependency_overrides[api.get_async_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        response = await client.get('/goods_transactions', params={'company_id': 9, 'date_from': '2026-01-01'})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload['total'] == 1
    assert payload['data'][0]['id'] == 10
