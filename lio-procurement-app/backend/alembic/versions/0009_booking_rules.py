"""organization booking rules

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-23

Spec 003: organization-specific commodity booking rules (deterministic
include / exclude terms, optional annualised amount limit, target group), an
append-only history of rule changes, how each request's commodity group was
decided (rule / system / manual / override, with the rule snapshot and any
override reason), and embeddings of commodity groups for the classification
shortlist. All additive; existing rows stay valid.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "booking_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("include_terms", sa.JSON(), nullable=False),
        sa.Column("exclude_terms", sa.JSON(), nullable=False),
        sa.Column("max_annual_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "target_commodity_group_id",
            sa.Integer(),
            sa.ForeignKey("commodity_groups.id"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "name", name="uq_booking_rule_org_name"),
    )
    op.create_index("ix_booking_rules_organization_id", "booking_rules", ["organization_id"])

    op.create_table(
        "booking_rule_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rule_id", sa.Uuid(), sa.ForeignKey("booking_rules.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_booking_rule_events_organization_id", "booking_rule_events", ["organization_id"]
    )

    op.add_column("procurement_requests", sa.Column("commodity_source", sa.String(), nullable=True))
    op.create_check_constraint(
        "ck_procurement_request_commodity_source",
        "procurement_requests",
        "commodity_source IN ('rule', 'system', 'manual', 'override')",
    )
    op.add_column("procurement_requests", sa.Column("booking_rule_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_procurement_requests_booking_rule_id",
        "procurement_requests",
        "booking_rules",
        ["booking_rule_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for name in ("booking_rule_name", "booking_rule_line", "override_reason"):
        op.add_column("procurement_requests", sa.Column(name, sa.Text(), nullable=True))

    op.add_column("commodity_groups", sa.Column("embedding", sa.LargeBinary(), nullable=True))
    op.add_column("commodity_groups", sa.Column("embedding_model", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("commodity_groups", "embedding_model")
    op.drop_column("commodity_groups", "embedding")
    for name in ("override_reason", "booking_rule_line", "booking_rule_name"):
        op.drop_column("procurement_requests", name)
    op.drop_constraint(
        "fk_procurement_requests_booking_rule_id", "procurement_requests", type_="foreignkey"
    )
    op.drop_column("procurement_requests", "booking_rule_id")
    op.drop_constraint(
        "ck_procurement_request_commodity_source", "procurement_requests", type_="check"
    )
    op.drop_column("procurement_requests", "commodity_source")
    op.drop_index("ix_booking_rule_events_organization_id", table_name="booking_rule_events")
    op.drop_table("booking_rule_events")
    op.drop_index("ix_booking_rules_organization_id", table_name="booking_rules")
    op.drop_table("booking_rules")
