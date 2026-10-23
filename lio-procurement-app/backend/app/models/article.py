import uuid

from sqlalchemy import ForeignKey, LargeBinary, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin


class Article(Base, CreatedAtMixin):
    """Reference catalog of purchasable articles, each tied to a supplier."""

    __tablename__ = "articles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_number: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="USD")
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    # Minimum order quantity; unit_price is per single unit (spec 002, FR-024).
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=1)
    # L2-normalised float32 vector of the description (migration 0008); NULL until
    # ``python -m app.embed_catalog`` (or the first lookup) computes it.
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String, nullable=True)

    supplier: Mapped["Supplier"] = relationship()


# Imported for the type-only forward reference in the relationship above.
from app.models.supplier import Supplier  # noqa: E402,F401
