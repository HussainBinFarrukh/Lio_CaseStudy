import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TimestampMixin


class BookingRule(Base, TimestampMixin):
    """An organization's accounting rule: items matching it are booked under a fixed group.

    Spec 003. Matching is deterministic (include / exclude terms, optional
    annualised amount limit) so the same request always gets the same group.
    """

    __tablename__ = "booking_rules"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_booking_rule_org_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    include_terms: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    exclude_terms: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Covered lines' annualised total must stay below this (e.g. "small" subscriptions).
    max_annual_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    target_commodity_group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("commodity_groups.id"), nullable=False
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class BookingRuleEvent(Base, CreatedAtMixin):
    """Append-only history of booking-rule changes (who changed what, when)."""

    __tablename__ = "booking_rule_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("booking_rules.id", ondelete="SET NULL"), nullable=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
