"""add fired marker to staff"""

from alembic import op
import sqlalchemy as sa


revision = '0012_staff_fired'
down_revision = '0011_service_labels'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('staff', schema='public'):
        return

    columns = {column['name'] for column in inspector.get_columns('staff', schema='public')}
    if 'fired' not in columns:
        op.add_column(
            'staff',
            sa.Column('fired', sa.Integer(), nullable=False, server_default='0'),
            schema='public',
        )

    indexes = {index['name'] for index in inspector.get_indexes('staff', schema='public')}
    if 'ix_staff_fired' not in indexes:
        op.create_index(
            'ix_staff_fired',
            'staff',
            ['fired'],
            schema='public',
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('staff', schema='public'):
        return

    indexes = {index['name'] for index in inspector.get_indexes('staff', schema='public')}
    if 'ix_staff_fired' in indexes:
        op.drop_index('ix_staff_fired', table_name='staff', schema='public')

    columns = {column['name'] for column in inspector.get_columns('staff', schema='public')}
    if 'fired' in columns:
        op.drop_column('staff', 'fired', schema='public')
