import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CommoditySource = Literal["rule", "system", "manual", "override"]

MAX_TERMS = 30
MAX_TERM_LENGTH = 80


def _clean_terms(terms: list[str]) -> list[str]:
    cleaned: list[str] = []
    for term in terms:
        term = " ".join(term.strip().split())
        if not term or term == "*":
            raise ValueError("Terms must not be empty.")
        if len(term) > MAX_TERM_LENGTH:
            raise ValueError(f"Terms must be at most {MAX_TERM_LENGTH} characters.")
        if term.casefold() not in {t.casefold() for t in cleaned}:
            cleaned.append(term)
    return cleaned


# ---------------------------------------------------------------------------
# Booking rules (admin resource, snake_case like other admin resources)
# ---------------------------------------------------------------------------


class BookingRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    include_terms: list[str] = Field(min_length=1, max_length=MAX_TERMS)
    exclude_terms: list[str] = Field(default_factory=list, max_length=MAX_TERMS)
    max_annual_amount: float | None = Field(default=None, gt=0)
    target_commodity_group_id: int
    active: bool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name must not be empty.")
        return value

    @field_validator("include_terms", "exclude_terms")
    @classmethod
    def clean_terms(cls, terms: list[str]) -> list[str]:
        return _clean_terms(terms)


class BookingRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    include_terms: list[str]
    exclude_terms: list[str]
    max_annual_amount: float | None
    target_commodity_group_id: int
    target_commodity_group_name: str | None = None
    active: bool
    created_at: datetime
    updated_at: datetime


class BookingRuleSaved(BaseModel):
    rule: BookingRuleOut
    # E.g. overlapping terms with another active rule (saved anyway).
    warnings: list[str] = Field(default_factory=list)


class BookingRuleEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    action: str
    summary: str
    detail: dict | None
    created_at: datetime


class MisbookedRequest(BaseModel):
    request_id: uuid.UUID
    title: str
    current_group_id: int | None
    mandated_group_id: int
    rule_id: uuid.UUID
    rule_name: str
    deciding_line: str
    created_at: datetime


class RebookRequest(BaseModel):
    request_ids: list[uuid.UUID] = Field(alias="requestIds", min_length=1, max_length=200)


class RebookResult(BaseModel):
    rebooked: int


# ---------------------------------------------------------------------------
# Classification (camelCase, feeds the New Request form like extraction)
# ---------------------------------------------------------------------------


class ClassificationLineIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    description: str = Field(default="", max_length=2000)
    quantity: float = Field(default=1, ge=0)
    unit_price: float | None = Field(default=None, ge=0, alias="unitPrice")
    total_price: float | None = Field(default=None, ge=0, alias="totalPrice")


class ClassificationRequest(BaseModel):
    lines: list[ClassificationLineIn] = Field(min_length=1, max_length=50)


class AppliedRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: uuid.UUID
    name: str
    target_group_id: int = Field(alias="targetGroupId")
    explanation: str


class DecidingLine(BaseModel):
    index: int
    description: str


class RuleHint(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    rule_id: uuid.UUID = Field(alias="ruleId")
    rule_name: str = Field(alias="ruleName")
    target_group_id: int = Field(alias="targetGroupId")
    line_index: int = Field(alias="lineIndex")
    message: str


class ClassificationOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    commodity_group_id: int | None = Field(default=None, alias="commodityGroupId")
    commodity_group_name: str | None = Field(default=None, alias="commodityGroupName")
    source: Literal["rule", "system"] | None = None
    rule: AppliedRule | None = None
    deciding_line: DecidingLine | None = Field(default=None, alias="decidingLine")
    split_advice: bool = Field(default=False, alias="splitAdvice")
    hints: list[RuleHint] = Field(default_factory=list)


# LLM-facing (internal): pick one group id from the shortlist.
class GroupPick(BaseModel):
    commodity_group_id: int | None
