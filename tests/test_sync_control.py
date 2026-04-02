from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, SyncState
from sync_control import SyncControlService


def test_set_state_serializes_datetime_to_isoformat():
    engine = create_engine(
        'sqlite+pysqlite:///:memory:',
        future=True,
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("ATTACH DATABASE ':memory:' AS system"))
    Base.metadata.create_all(engine, tables=[SyncState.__table__])
    session_local = sessionmaker(bind=engine)
    session = session_local()
    service = SyncControlService()
    value = datetime(2026, 3, 29, 10, 30, 45, 123456)

    try:
        service.set_state(session, 'last_run_started_at', value)

        saved = session.get(SyncState, 'last_run_started_at')
        assert saved is not None
        assert saved.value == '2026-03-29T10:30:45.123456'
    finally:
        session.close()
        engine.dispose()
