"""Force-import plan metrics and service labels from Google Sheets."""
import asyncio
import sys

from config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER
from database import build_async_database_url
from plan_import import import_plan_sheet_from_config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def main():
    engine = create_async_engine(
        build_async_database_url(DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD),
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            result = await import_plan_sheet_from_config(session)
    finally:
        await engine.dispose()

    imported = int(result.get('imported') or 0)
    skipped = result.get('skipped') or []
    services = result.get('services') or {}
    svc_imported = int(services.get('imported') or 0)
    svc_skipped = services.get('skipped') or []

    print(f'plan_metrics: imported={imported}, skipped={skipped}')
    print(f'service_labels: imported={svc_imported}, skipped={svc_skipped}')

    failed = []
    if skipped and not imported:
        failed.append(f'plan_metrics: {skipped}')
    if svc_skipped and not svc_imported:
        failed.append(f'service_labels: {svc_skipped}')
    if failed:
        print(f'! Import failed: {"; ".join(failed)}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
