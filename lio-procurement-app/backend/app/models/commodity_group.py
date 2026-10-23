from sqlalchemy import Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class CommodityGroup(Base, CreatedAtMixin):
    """Reference data: the fixed procurement commodity groups (global taxonomy)."""

    __tablename__ = "commodity_groups"

    # IDs are fixed (1-50) reference values, not auto-generated.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Vector of "category / name" for the classification shortlist (migration 0009).
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String, nullable=True)
