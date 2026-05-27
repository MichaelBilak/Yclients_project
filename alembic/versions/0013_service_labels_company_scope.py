"""scope service labels by company"""

from alembic import op
import sqlalchemy as sa


revision = '0013_service_labels_scope'
down_revision = '0012_staff_fired'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('service_labels', schema='public'):
        return

    pk = inspector.get_pk_constraint('service_labels', schema='public') or {}
    constrained_columns = pk.get('constrained_columns') or []
    if constrained_columns == ['service_id', 'company_id']:
        return

    pk_name = pk.get('name') or 'service_labels_pkey'
    op.drop_constraint(pk_name, 'service_labels', schema='public', type_='primary')
    op.create_primary_key(
        'service_labels_pkey',
        'service_labels',
        ['service_id', 'company_id'],
        schema='public',
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('service_labels', schema='public'):
        return

    pk = inspector.get_pk_constraint('service_labels', schema='public') or {}
    constrained_columns = pk.get('constrained_columns') or []
    if constrained_columns == ['service_id']:
        return

    pk_name = pk.get('name') or 'service_labels_pkey'
    op.drop_constraint(pk_name, 'service_labels', schema='public', type_='primary')
    op.create_primary_key(
        'service_labels_pkey',
        'service_labels',
        ['service_id'],
        schema='public',
    )
