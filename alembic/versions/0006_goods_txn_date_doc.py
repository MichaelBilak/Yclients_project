"""backfill goods transaction sale dates by document"""

from alembic import op
import sqlalchemy as sa


revision = '0006_goods_txn_date_doc'
down_revision = '0005_goods_transactions_date'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        WITH financial_document_dates AS (
            SELECT
                document_id,
                company_id,
                MIN(date) AS date
            FROM public.financial_transactions
            WHERE document_id IS NOT NULL
              AND company_id IS NOT NULL
              AND date IS NOT NULL
            GROUP BY document_id, company_id
        )
        UPDATE public.goods_transactions gt
        SET date = fdd.date
        FROM financial_document_dates fdd
        WHERE gt.date IS NULL
          AND gt.type_id = 1
          AND gt.document_id = fdd.document_id
          AND gt.company_id = fdd.company_id
    """))


def downgrade() -> None:
    pass
