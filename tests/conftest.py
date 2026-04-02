from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from models import (
    Account,
    Appointment,
    Client,
    Comment,
    Company,
    FinancialTransaction,
    Good,
    GoodCategory,
    GoodTransaction,
    Group,
    Service,
    ServiceCategory,
    Staff,
    StaffPosition,
    StaffSchedule,
    Storage,
    Transaction,
    Base,
)


PUBLIC_TABLES = [
    Group.__table__,
    Company.__table__,
    ServiceCategory.__table__,
    Service.__table__,
    StaffPosition.__table__,
    Staff.__table__,
    Client.__table__,
    Account.__table__,
    Storage.__table__,
    GoodCategory.__table__,
    Good.__table__,
    Appointment.__table__,
    Transaction.__table__,
    FinancialTransaction.__table__,
    GoodTransaction.__table__,
    Comment.__table__,
    StaffSchedule.__table__,
]


@pytest_asyncio.fixture
async def async_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=PUBLIC_TABLES)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()
