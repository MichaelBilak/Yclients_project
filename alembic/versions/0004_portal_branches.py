"""portal accounts and branch mapping for future multi-salon UI"""

from alembic import op
import sqlalchemy as sa

revision = '0004_portal_branches'
down_revision = '0003_sys_dt_varchar'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'portal_accounts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('label', sa.String(length=255), nullable=False, server_default='default'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        schema='system',
    )
    op.create_table(
        'portal_branches',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('portal_account_id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['portal_account_id'],
            ['system.portal_accounts.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['company_id'],
            ['public.companies.id'],
            ondelete='CASCADE',
        ),
        sa.UniqueConstraint(
            'portal_account_id',
            'company_id',
            name='uq_portal_branch_account_company',
        ),
        schema='system',
    )
    op.execute(sa.text("""
        INSERT INTO system.portal_accounts (label)
        SELECT 'default'
        WHERE NOT EXISTS (SELECT 1 FROM system.portal_accounts)
    """))


def downgrade() -> None:
    op.drop_table('portal_branches', schema='system')
    op.drop_table('portal_accounts', schema='system')
