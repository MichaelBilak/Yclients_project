from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, Company, Group, Staff
from sync_pipeline import sync_staff


class FakeYClientsAPI:
    def __init__(self, staff):
        self._staff = staff

    def get_staff(self, company_id):
        return self._staff


def test_sync_staff_marks_missing_staff_as_fired():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine, tables=[Group.__table__, Company.__table__, Staff.__table__])
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        db.add(Group(id=1, title='G1'))
        db.add(Company(id=1, title='Salon', group_id=1))
        db.add(Staff(id=1, name='Existing', company_id=1, fired=0))
        db.add(Staff(id=2, name='Stale', company_id=1, fired=0))
        db.commit()

        api = FakeYClientsAPI([
            {
                'id': 1,
                'name': 'Existing',
                'fired': 0,
                'position': {'title': 'Барбер'},
            },
        ])

        assert sync_staff(api, db, '1') is True

        active = db.get(Staff, 1)
        stale = db.get(Staff, 2)
        assert active.fired == 0
        assert stale.fired == 1
    finally:
        db.close()
        engine.dispose()
