from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.numbers import parse_amount, parse_percent


class PdfParseResponse(BaseModel):
    text: str


class ExtractionRequest(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# LLM-facing schema (internal). Sent to the model as a Structured Outputs JSON
# schema, so every field is required-but-nullable and has no default: the model
# must say "absent" (null) instead of inventing "" or 0.
# ---------------------------------------------------------------------------

PositionKind = Literal["item", "alternative", "heading", "promotional"]

AbsentField = Literal[
    "vendor_name",
    "vendor_tax_id",
    "quote_number",
    "quote_date",
    "valid_until",
    "net_total",
    "shipping",
    "tax",
    "fees",
    "grand_total",
]


class LlmPosition(BaseModel):
    item_no: str | None
    kind: PositionKind
    description: str
    quantity: float | None
    unit: str | None
    unit_price: float | None
    discount_percent: float | None
    line_total: float | None
    price_note: str | None

    # Defense in depth: tolerate "$1,409.06" / "-20.00%" should a model ever
    # return strings despite the schema.
    @field_validator("quantity", "unit_price", "line_total", mode="before")
    @classmethod
    def parse_amounts(cls, value: object) -> float | None:
        return parse_amount(value)

    @field_validator("discount_percent", mode="before")
    @classmethod
    def parse_discount(cls, value: object) -> float | None:
        return parse_percent(value)


class LlmQuote(BaseModel):
    title: str | None
    # Generated before vendor_name (Structured Outputs keeps field order) so the
    # model separates the addressee from the issuer before naming the vendor.
    recipient_name: str | None
    vendor_evidence: str | None
    vendor_name: str | None
    vendor_tax_id: str | None
    quote_number: str | None
    quote_date: str | None
    valid_until: str | None
    currency: str | None
    positions: list[LlmPosition]
    net_total: float | None
    shipping: float | None
    tax: float | None
    fees: float | None
    grand_total: float | None
    absent_fields: list[AbsentField]

    @field_validator("net_total", "shipping", "tax", "fees", "grand_total", mode="before")
    @classmethod
    def parse_amounts(cls, value: object) -> float | None:
        return parse_amount(value)


# ---------------------------------------------------------------------------
# API response (camelCase on the wire — what the frontend's extraction flow
# consumes). Existing keys keep their names and types; new keys are additive.
# ---------------------------------------------------------------------------

FieldStatus = Literal["extracted", "not_in_document", "could_not_extract"]
ExcludedReason = Literal["alternative", "heading", "promotional"]
ReconciliationScope = Literal["line", "net_total", "grand_total"]
ExtractionErrorCode = Literal[
    "not_configured", "service_busy", "refused", "too_long", "unreadable"
]


class OrderLineData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    position_description: str = Field(default="", alias="positionDescription")
    unit_price: float = Field(default=0, alias="unitPrice")
    amount: float = 1
    unit: str = ""
    discount_percent: float = Field(default=0, alias="discountPercent")
    # Net of discount.
    total_price: float = Field(default=0, alias="totalPrice")


class QuoteTotals(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    net_total: float | None = Field(default=None, alias="netTotal")
    shipping: float | None = None
    tax: float | None = None
    fees: float | None = None
    grand_total: float | None = Field(default=None, alias="grandTotal")


class ExcludedPosition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    item_no: str | None = Field(default=None, alias="itemNo")
    description: str
    amount: float | None = None
    reason: ExcludedReason


class ReconciliationFinding(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    scope: ReconciliationScope
    line_index: int | None = Field(default=None, alias="lineIndex")
    expected: float
    extracted: float


class ExtractedVendorData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = ""
    vendor_name: str = Field(default="", alias="vendorName")
    vat_id: str = Field(default="", alias="vatId")
    department: str = ""
    quote_number: str | None = Field(default=None, alias="quoteNumber")
    quote_date: str | None = Field(default=None, alias="quoteDate")  # YYYY-MM-DD
    valid_until: str | None = Field(default=None, alias="validUntil")  # YYYY-MM-DD
    currency: str = "USD"
    order_lines: list[OrderLineData] = Field(default_factory=list, alias="orderLines")
    totals: QuoteTotals = Field(default_factory=QuoteTotals)
    # Grand total (net + shipping + tax + fees).
    total_cost: float = Field(default=0, alias="totalCost")
    commodity_group_id: int | None = Field(default=None, alias="commodityGroupId")
    commodity_group_name: str | None = Field(default=None, alias="commodityGroupName")
    excluded_positions: list[ExcludedPosition] = Field(
        default_factory=list, alias="excludedPositions"
    )
    reconciliation: list[ReconciliationFinding] = Field(default_factory=list)
    field_status: dict[str, FieldStatus] = Field(default_factory=dict, alias="fieldStatus")


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success: bool
    extraction_id: str | None = Field(default=None, alias="extractionId")
    data: ExtractedVendorData | None = None
    error: str | None = None
    error_code: ExtractionErrorCode | None = Field(default=None, alias="errorCode")
    missing_fields: list[str] | None = Field(default=None, alias="missingFields")
