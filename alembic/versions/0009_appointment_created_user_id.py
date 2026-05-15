"""add created_user_id to appointments"""

from alembic import op
import sqlalchemy as sa


revision = '0009_appointment_created_user_id'
down_revision = '0008_staff_plan_metrics'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('appointments', schema='public'):
        return

    columns = {column['name'] for column in inspector.get_columns('appointments', schema='public')}
    if 'created_user_id' not in columns:
        op.add_column(
            'appointments',
            sa.Column('created_user_id', sa.Integer(), nullable=True),
            schema='public',
        )

    indexes = {index['name'] for index in inspector.get_indexes('appointments', schema='public')}
    if 'ix_appointments_created_user_id' not in indexes:
        op.create_index(
            'ix_appointments_created_user_id',
            'appointments',
            ['created_user_id'],
            schema='public',
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('appointments', schema='public'):
        return

    indexes = {index['name'] for index in inspector.get_indexes('appointments', schema='public')}
    if 'ix_appointments_created_user_id' in indexes:
        op.drop_index(
            'ix_appointments_created_user_id',
            table_name='appointments',
            schema='public',
        )

    columns = {column['name'] for column in inspector.get_columns('appointments', schema='public')}
    if 'created_user_id' in columns:
        op.drop_column('appointments', 'created_user_id', schema='public')
