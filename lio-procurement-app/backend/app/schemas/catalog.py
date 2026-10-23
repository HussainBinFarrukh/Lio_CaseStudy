import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# camelCase on the wire, like the extraction service: both feed the New Request
# form directly.


class SuggestionLineIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    key: str = Field(max_length=64)
    description: str = Field(default="", max_length=2000)
    unit: str = ""
    quantity: float = Field(default=0, ge=0)
    unit_price: float | None = Field(default=None, ge=0, alias="unitPrice")
    discount_percent: float = Field(default=0, ge=0, lt=100, alias="discountPercent")
    # Net of discount; preferred over unit price when present.
    total_price: float | None = Field(default=None, ge=0, alias="totalPrice")
    currency: str = "USD"


class SuggestionsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    lines: list[SuggestionLineIn] = Field(min_length=1, max_length=50)
    vendor_name: str | None = Field(default=None, alias="vendorName")
    vendor_vat_id: str | None = Field(default=None, alias="vendorVatId")
    limit: int = Field(default=3, ge=1, le=5)


class ArticleSuggestion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    article_id: uuid.UUID = Field(alias="articleId")
    article_number: str = Field(alias="articleNumber")
    description: str
    supplier_id: uuid.UUID = Field(alias="supplierId")
    supplier_name: str = Field(alias="supplierName")
    # Lets the requester switch the request's vendor to this supplier (FR-016).
    supplier_vat_id: str | None = Field(default=None, alias="supplierVatId")
    unit_price: float = Field(alias="unitPrice")
    unit: str
    currency: str
    min_quantity: float = Field(alias="minQuantity")
    relevance: float
    # Price comparison with the line (only when units and currency are comparable).
    comparable: bool = False
    unit_difference: float | None = Field(default=None, alias="unitDifference")
    # unit_difference × quantity: negative = saving, positive = more expensive.
    line_effect: float | None = Field(default=None, alias="lineEffect")
    below_min_quantity: bool = Field(default=False, alias="belowMinQuantity")
    from_vendor: bool = Field(default=False, alias="fromVendor")


class AgreementCheck(BaseModel):
    """The vendor is a contracted supplier and quotes above its own catalog price."""

    model_config = ConfigDict(populate_by_name=True)

    article_number: str = Field(alias="articleNumber")
    negotiated_price: float = Field(alias="negotiatedPrice")
    difference: float  # per unit, > 0


class LineSuggestions(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    key: str
    suggestions: list[ArticleSuggestion] = Field(default_factory=list)
    agreement_check: AgreementCheck | None = Field(default=None, alias="agreementCheck")


class ContractedSupplier(BaseModel):
    id: uuid.UUID
    name: str


class SuggestionsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: Literal["semantic", "lexical"]
    contracted_supplier: ContractedSupplier | None = Field(
        default=None, alias="contractedSupplier"
    )
    lines: list[LineSuggestions]


class CatalogUsage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    request_count: int = Field(alias="requestCount")
    line_count: int = Field(alias="lineCount")
    linked_line_count: int = Field(alias="linkedLineCount")
    linked_share: float = Field(alias="linkedShare")
    realised_savings: float = Field(alias="realisedSavings")
    missed_savings: float = Field(alias="missedSavings")


# ---------------------------------------------------------------------------
# LLM-facing (internal): the relevance check returns one boolean per candidate.
# ---------------------------------------------------------------------------


class RelevanceVerdict(BaseModel):
    same_kind: list[bool]
