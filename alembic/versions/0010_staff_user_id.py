"""add user_id to staff (link to YClients system user)"""

from alembic import op
import sqlalchemy as sa


revision = '0010_staff_user_id'
down_revision = '0009_appointment_created_user_id'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('staff', schema='public'):
        return

    columns = {column['name'] for column in inspector.get_columns('staff', schema='public')}
    if 'user_id' not in columns:
        op.add_column(
            'staff',
            sa.Column('user_id', sa.Integer(), nullable=True),
            schema='public',
        )

    indexes = {index['name'] for index in inspector.get_indexes('staff', schema='public')}
    if 'ix_staff_user_id' not in indexes:
        op.create_index(
            'ix_staff_user_id',
            'staff',
            ['user_id'],
            schema='public',
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('staff', schema='public'):
        return

    indexes = {index['name'] for index in inspector.get_indexes('staff', schema='public')}
    if 'ix_staff_user_id' in indexes:
        op.drop_index('ix_staff_user_id', table_name='staff', schema='public')

    columns = {column['name'] for column in inspector.get_columns('staff', schema='public')}
    if 'user_id' in columns:
        op.drop_column('staff', 'user_id', schema='public')
