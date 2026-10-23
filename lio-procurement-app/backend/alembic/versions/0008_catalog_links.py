"""catalog links on order lines

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-23

Spec 002 (catalog article suggestions): stores an embedding per catalog article
for semantic matching, and on each order line the catalog agreement it uses
(article reference plus a snapshot of number, description, supplier, negotiated
price and minimum quantity, and the quoted price it replaced) or, for lines that
don't use one, the cheapest unused catalog alternative and its potential saving.
All columns are nullable, so existing rows stay valid unchanged.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ARTICLE_COLUMNS = [
    sa.Column("embedding", sa.LargeBinary(), nullable=True),
    sa.Column("embedding_model", sa.String(), nullable=True),
]

_LINE_COLUMNS = [
    sa.Column("article_number", sa.Text(), nullable=True),
    sa.Column("article_description", sa.Text(), nullable=True),
    sa.Column("article_supplier_name", sa.Text(), nullable=True),
    sa.Column("negotiated_unit_price", sa.Numeric(12, 2), nullable=True),
    sa.Column("article_min_quantity", sa.Numeric(12, 3), nullable=True),
    sa.Column("original_unit_price", sa.Numeric(12, 2), nullable=True),
    sa.Column("alternative_article_number", sa.Text(), nullable=True),
    sa.Column("alternative_supplier_name", sa.Text(), nullable=True),
    sa.Column("alternative_unit_price", sa.Numeric(12, 2), nullable=True),
    sa.Column("potential_saving", sa.Numeric(12, 2), nullable=True),
]


def upgrade() -> None:
    for column in _ARTICLE_COLUMNS:
        op.add_column("articles", column)

    op.add_column("order_lines", sa.Column("catalog_article_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_order_lines_catalog_article_id",
        "order_lines",
        "articles",
        ["catalog_article_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_order_lines_catalog_article_id", "order_lines", ["catalog_article_id"]
    )
    for column in _LINE_COLUMNS:
        op.add_column("order_lines", column)


def downgrade() -> None:
    for column in reversed(_LINE_COLUMNS):
        op.drop_column("order_lines", column.name)
    op.drop_index("ix_order_lines_catalog_article_id", table_name="order_lines")
    op.drop_constraint(
        "fk_order_lines_catalog_article_id", "order_lines", type_="foreignkey"
    )
    op.drop_column("order_lines", "catalog_article_id")
    for column in reversed(_ARTICLE_COLUMNS):
        op.drop_column("articles", column.name)
