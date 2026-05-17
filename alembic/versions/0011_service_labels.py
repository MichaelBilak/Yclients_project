"""add dashboard service labels"""

from alembic import op
import sqlalchemy as sa


revision = '0011_service_labels'
down_revision = '0010_staff_user_id'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table('service_labels', schema='public'):
        return

    op.create_table(
        'service_labels',
        sa.Column('service_id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('is_extra', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('source', sa.String(), nullable=True, server_default='google_sheet'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['service_id'], ['public.services.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['public.companies.id'], ondelete='CASCADE'),
        schema='public',
    )
    op.create_index('ix_service_labels_company_id', 'service_labels', ['company_id'], schema='public')
    op.create_index('ix_service_labels_is_extra', 'service_labels', ['is_extra'], schema='public')


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('service_labels', schema='public'):
        return

    indexes = {index['name'] for index in inspector.get_indexes('service_labels', schema='public')}
    if 'ix_service_labels_is_extra' in indexes:
        op.drop_index('ix_service_labels_is_extra', table_name='service_labels', schema='public')
    if 'ix_service_labels_company_id' in indexes:
        op.drop_index('ix_service_labels_company_id', table_name='service_labels', schema='public')
    op.drop_table('service_labels', schema='public')
