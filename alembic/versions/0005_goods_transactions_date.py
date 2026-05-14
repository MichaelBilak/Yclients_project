"""add date column to goods_transactions"""

from alembic import op
import sqlalchemy as sa


revision = '0005_goods_transactions_date'
down_revision = '0004_portal_branches'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'goods_transactions',
        sa.Column('date', sa.DateTime(), nullable=True),
        schema='public',
    )
    op.create_index(
        'ix_goods_transactions_date',
        'goods_transactions',
        ['date'],
        schema='public',
    )

    op.execute(sa.text("""
        UPDATE public.goods_transactions gt
        SET date = ft.date
        FROM public.financial_transactions ft
        WHERE ft.sold_item_type = 'goods_transaction'
          AND ft.sold_item_id = gt.id
          AND gt.date IS NULL
    """))


def downgrade() -> None:
    op.drop_index(
        'ix_goods_transactions_date',
        table_name='goods_transactions',
        schema='public',
    )
    op.drop_column('goods_transactions', 'date', schema='public')
