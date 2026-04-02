"""normalize varchar system datetime columns"""

from alembic import op
import sqlalchemy as sa

revision = '0003_sys_dt_varchar'
down_revision = '0002_system_datetime_columns'
branch_labels = None
depends_on = None


SYSTEM_TIMESTAMP_COLUMNS = {
    'sync_state': ['updated_at'],
    'sync_runs': ['started_at', 'finished_at'],
    'sync_step_runs': ['created_at'],
}


def _column_type(bind, table_name: str, column_name: str) -> str | None:
    return bind.execute(sa.text("""
        SELECT data_type
        FROM information_schema.columns
        WHERE table_schema = 'system'
          AND table_name = :table_name
          AND column_name = :column_name
    """), {'table_name': table_name, 'column_name': column_name}).scalar()


def upgrade() -> None:
    bind = op.get_bind()
    for table_name, columns in SYSTEM_TIMESTAMP_COLUMNS.items():
        for column_name in columns:
            if _column_type(bind, table_name, column_name) == 'character varying':
                op.execute(sa.text(f"""
                    ALTER TABLE system.{table_name}
                    ALTER COLUMN {column_name}
                    TYPE timestamp without time zone
                    USING NULLIF({column_name}, '')::timestamp
                """))


def downgrade() -> None:
    bind = op.get_bind()
    for table_name, columns in SYSTEM_TIMESTAMP_COLUMNS.items():
        for column_name in columns:
            if _column_type(bind, table_name, column_name) == 'timestamp without time zone':
                op.execute(sa.text(f"""
                    ALTER TABLE system.{table_name}
                    ALTER COLUMN {column_name}
                    TYPE varchar
                    USING CASE
                        WHEN {column_name} IS NULL THEN NULL
                        ELSE to_char({column_name}, 'YYYY-MM-DD\"T\"HH24:MI:SS.US')
                    END
                """))
