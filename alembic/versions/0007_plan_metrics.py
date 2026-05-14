"""add manually maintained plan metrics"""

from alembic import op
import sqlalchemy as sa


revision = '0007_plan_metrics'
down_revision = '0006_goods_txn_date_doc'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table('plan_metrics', schema='public'):
        return

    op.create_table(
        'plan_metrics',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('metric_code', sa.String(), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('source', sa.String(), nullable=True, server_default='manual'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['company_id'], ['public.companies.id'], ondelete='CASCADE'),
        sa.UniqueConstraint(
            'period_start',
            'period_end',
            'company_id',
            'metric_code',
            name='uq_plan_metric_period_company_metric',
        ),
        schema='public',
    )
    op.create_index('ix_plan_metrics_period_start', 'plan_metrics', ['period_start'], schema='public')
    op.create_index('ix_plan_metrics_period_end', 'plan_metrics', ['period_end'], schema='public')
    op.create_index('ix_plan_metrics_company_id', 'plan_metrics', ['company_id'], schema='public')
    op.create_index('ix_plan_metrics_metric_code', 'plan_metrics', ['metric_code'], schema='public')


def downgrade() -> None:
    op.drop_table('plan_metrics', schema='public')
