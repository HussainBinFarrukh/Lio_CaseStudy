"""quote details on requests

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-22

Captures what reliable quote extraction reads from a vendor offer so buyers can
reference it later: quote number and dates, currency, the totals breakdown
(net, shipping, tax, fees — ``total_cost`` remains the grand total) and a
per-line discount. All columns are additive: request columns are nullable and
``discount_percent`` defaults to 0, so existing rows stay valid unchanged.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUEST_COLUMNS = [
    sa.Column("quote_number", sa.Text(), nullable=True),
    sa.Column("quote_date", sa.Date(), nullable=True),
    sa.Column("quote_valid_until", sa.Date(), nullable=True),
    sa.Column("currency", sa.String(3), nullable=True),
    sa.Column("net_total", sa.Numeric(12, 2), nullable=True),
    sa.Column("shipping_amount", sa.Numeric(12, 2), nullable=True),
    sa.Column("tax_amount", sa.Numeric(12, 2), nullable=True),
    sa.Column("fees_amount", sa.Numeric(12, 2), nullable=True),
]


def upgrade() -> None:
    for column in _REQUEST_COLUMNS:
        op.add_column("procurement_requests", column)
    op.add_column(
        "order_lines",
        sa.Column(
            "discount_percent", sa.Numeric(5, 2), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    op.drop_column("order_lines", "discount_percent")
    for column in reversed(_REQUEST_COLUMNS):
        op.drop_column("procurement_requests", column.name)
