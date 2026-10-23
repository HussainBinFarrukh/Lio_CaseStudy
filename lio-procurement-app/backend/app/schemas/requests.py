import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

RequestStatus = Literal["open", "in_progress", "closed"]
ApprovalStatus = Literal["pending", "approved", "rejected"]


# ---------------------------------------------------------------------------
# Inputs (camelCase — matches what the frontend forms already send)
# ---------------------------------------------------------------------------

class OrderLineIn(BaseModel):
    position_description: str = Field(alias="positionDescription")
    unit_price: float = Field(alias="unitPrice")
    amount: float
    unit: str
    discount_percent: float = Field(default=0, ge=0, lt=100, alias="discountPercent")
    # Net of discount.
    total_price: float = Field(alias="totalPrice")
    # Catalog agreement applied to this line (spec 002). The server copies the
    # article's number, supplier and negotiated price from the catalog itself.
    catalog_article_id: uuid.UUID | None = Field(default=None, alias="catalogArticleId")
    # The quoted price before the article was applied (realised-savings basis).
    original_unit_price: float | None = Field(default=None, ge=0, alias="originalUnitPrice")


class QuoteDetailsIn(BaseModel):
    """Optional vendor-quote details captured at extraction (all nullable)."""

    quote_number: str | None = Field(default=None, alias="quoteNumber")
    quote_date: date | None = Field(default=None, alias="quoteDate")
    quote_valid_until: date | None = Field(default=None, alias="validUntil")
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    net_total: float | None = Field(default=None, ge=0, alias="netTotal")
    shipping_amount: float | None = Field(default=None, ge=0, alias="shippingAmount")
    tax_amount: float | None = Field(default=None, ge=0, alias="taxAmount")
    fees_amount: float | None = Field(default=None, ge=0, alias="feesAmount")

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @field_validator("quote_number")
    @classmethod
    def blank_quote_number(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None


# Request columns set from QuoteDetailsIn (same names on both sides).
QUOTE_DETAIL_FIELDS = tuple(QuoteDetailsIn.model_fields)


class RequestCreate(QuoteDetailsIn):
    requestor_name: str = Field(alias="requestorName")
    title: str = Field(alias="titleShortDescription")
    vendor_name: str = Field(alias="vendorName")
    vat_id: str | None = Field(default=None, alias="vatId")
    commodity_group_id: int = Field(alias="commodityGroupId")
    total_cost: float = Field(alias="totalCost")
    department: str | None = None
    order_lines: list[OrderLineIn] = Field(alias="orderLines", min_length=1)


class RequestUpdate(QuoteDetailsIn):
    requestor_name: str = Field(alias="requestorName")
    title: str
    vendor_name: str = Field(alias="vendorName")
    vat_id: str | None = Field(default=None, alias="vatId")
    commodity_group_id: int = Field(alias="commodityGroupId")
    total_cost: float = Field(alias="totalCost")
    department: str | None = None
    order_lines: list[OrderLineIn] = Field(alias="orderLines")


class StatusUpdate(BaseModel):
    status: RequestStatus


class ApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]


# ---------------------------------------------------------------------------
# Outputs (snake_case — matches the DB row shapes the frontend renders)
# ---------------------------------------------------------------------------

class CommodityGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: str
    name: str


class OrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    request_id: uuid.UUID
    position_description: str
    unit_price: float
    amount: float
    unit: str
    discount_percent: float
    total_price: float
    line_order: int
    created_at: datetime
    # Catalog agreement used (snapshot at linking time).
    catalog_article_id: uuid.UUID | None = None
    article_number: str | None = None
    article_description: str | None = None
    article_supplier_name: str | None = None
    negotiated_unit_price: float | None = None
    article_min_quantity: float | None = None
    original_unit_price: float | None = None
    # Cheapest matching catalog article that was not used.
    alternative_article_number: str | None = None
    alternative_supplier_name: str | None = None
    alternative_unit_price: float | None = None
    potential_saving: float | None = None


class RequestActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    request_id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    summary: str
    detail: dict | None
    created_at: datetime


class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID | None
    created_by: uuid.UUID | None
    requestor_name: str
    title: str
    vendor_name: str
    vat_id: str | None
    commodity_group_id: int | None
    department: str | None
    status: RequestStatus
    approval_status: ApprovalStatus
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    total_cost: float | None
    net_total: float | None
    shipping_amount: float | None
    tax_amount: float | None
    fees_amount: float | None
    currency: str | None
    quote_number: str | None
    quote_date: date | None
    quote_valid_until: date | None
    created_at: datetime
    updated_at: datetime
    order_lines: list[OrderLineOut]
    # Serialized as ``commodity_groups`` (the join key the frontend renders) but
    # read from the ORM's ``commodity_group`` relationship.
    commodity_groups: CommodityGroupOut | None = Field(
        default=None, validation_alias="commodity_group"
    )

    @computed_field
    @property
    def potential_saving_total(self) -> float | None:
        """Total saving available from catalog alternatives that were not used."""
        savings = [line.potential_saving for line in self.order_lines if line.potential_saving]
        return round(sum(savings), 2) if savings else None
