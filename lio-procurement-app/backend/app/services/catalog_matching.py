"""Deterministic rules for catalog suggestions (spec 002).

Matching decides *which* articles are the same kind of item (see
``catalog_search``); everything here is pure: unit comparability, price
comparison, ranking, minimum order quantity and contracted-supplier
recognition. No I/O, so it is tested without the AI service.
"""
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.schemas.catalog import AgreementCheck, ArticleSuggestion, SuggestionLineIn
from app.services.quote_rules import normalize_company, normalize_ein

# Units printed on quotes vs. catalog units, mapped to one comparable form.
_UNIT_ALIASES = {
    "piece": {"piece", "pieces", "pc", "pcs", "ea", "each", "unit", "units", "item", "items"},
    "sq ft": {"sq ft", "sqft", "sq. ft.", "sq.ft.", "square foot", "square feet", "ft2"},
    "ft": {"ft", "feet", "foot", "lin ft", "linear ft", "linear feet"},
    "hour": {"hour", "hours", "hr", "hrs", "h"},
    "day": {"day", "days"},
    "month": {"month", "months", "mo"},
    "license": {"license", "licenses", "licence", "licences", "seat", "seats"},
    "set": {"set", "sets"},
    "pack": {"pack", "packs", "package", "packages"},
    "roll": {"roll", "rolls"},
    "pallet": {"pallet", "pallets"},
    "lb": {"lb", "lbs", "pound", "pounds"},
    "gal": {"gal", "gallon", "gallons"},
}
_UNIT_LOOKUP = {alias: unit for unit, aliases in _UNIT_ALIASES.items() for alias in aliases}
_TOKEN = re.compile(r"[a-z0-9]+")


def normalize_unit(unit: str | None) -> str:
    text = re.sub(r"\s+", " ", (unit or "").strip().casefold()).rstrip(".")
    return _UNIT_LOOKUP.get(text, text)


def normalize_text(text: str | None) -> str:
    return " ".join(_TOKEN.findall((text or "").casefold()))


def line_net_unit_price(line: SuggestionLineIn) -> float | None:
    """The price actually paid per unit: after discount (Greenmantle 715.26, not 894.08)."""
    if line.total_price is not None and line.quantity > 0 and line.total_price > 0:
        return line.total_price / line.quantity
    if line.unit_price is not None and line.unit_price > 0:
        return line.unit_price * (1 - line.discount_percent / 100)
    return None


@dataclass(frozen=True)
class CatalogArticle:
    """The fields of an organization's catalog article that suggestions need."""

    id: uuid.UUID
    article_number: str
    description: str
    supplier_id: uuid.UUID
    supplier_name: str
    unit_price: float
    unit: str
    currency: str
    min_quantity: float
    supplier_vat_id: str | None = None


def build_suggestion(
    article: CatalogArticle,
    line: SuggestionLineIn,
    *,
    relevance: float,
    vendor_supplier_id: uuid.UUID | None,
) -> ArticleSuggestion:
    """Compare one article with one line (units, currency, net price, MOQ)."""
    line_price = line_net_unit_price(line)
    comparable = (
        line_price is not None
        and line.quantity > 0
        and normalize_unit(line.unit) == normalize_unit(article.unit)
        and (line.currency or "USD").upper() == article.currency.upper() == "USD"
    )
    unit_difference = line_effect = None
    if comparable:
        unit_difference = round(article.unit_price - line_price, 2)
        line_effect = round((article.unit_price - line_price) * line.quantity, 2)
    return ArticleSuggestion(
        article_id=article.id,
        article_number=article.article_number,
        description=article.description,
        supplier_id=article.supplier_id,
        supplier_name=article.supplier_name,
        supplier_vat_id=article.supplier_vat_id,
        unit_price=article.unit_price,
        unit=article.unit,
        currency=article.currency,
        min_quantity=article.min_quantity,
        relevance=round(relevance, 4),
        comparable=comparable,
        unit_difference=unit_difference,
        line_effect=line_effect,
        below_min_quantity=line.quantity > 0 and article.min_quantity > line.quantity,
        from_vendor=vendor_supplier_id is not None and article.supplier_id == vendor_supplier_id,
    )


def rank(suggestions: Iterable[ArticleSuggestion], limit: int) -> list[ArticleSuggestion]:
    """Contracted supplier's own articles first, then relevance, then lowest price.

    Articles with the same description share one relevance score, so the
    cheapest offer of an identical item wins (toner cyan: $95, $117, $139).
    """
    ordered = sorted(
        suggestions,
        key=lambda s: (not s.from_vendor, -s.relevance, s.unit_price, s.article_number),
    )
    return ordered[:limit]


def agreement_check(suggestions: Sequence[ArticleSuggestion]) -> AgreementCheck | None:
    """The vendor's own catalog article is cheaper than what the vendor quoted (US3)."""
    for suggestion in suggestions:
        if (
            suggestion.from_vendor
            and suggestion.comparable
            and suggestion.unit_difference is not None
            and suggestion.unit_difference < 0
        ):
            return AgreementCheck(
                article_number=suggestion.article_number,
                negotiated_price=suggestion.unit_price,
                difference=round(-suggestion.unit_difference, 2),
            )
    return None


def best_cheaper_alternative(
    suggestions: Sequence[ArticleSuggestion],
) -> ArticleSuggestion | None:
    """The cheapest comparable suggestion that would have saved money, if any."""
    cheaper = [s for s in suggestions if s.comparable and (s.line_effect or 0) < 0]
    return min(cheaper, key=lambda s: (s.unit_price, s.article_number), default=None)


@dataclass(frozen=True)
class SupplierRef:
    id: uuid.UUID
    name: str
    vat_id: str | None


def match_supplier(
    vendor_name: str | None, vendor_vat_id: str | None, suppliers: Iterable[SupplierRef]
) -> SupplierRef | None:
    """Recognise the request's vendor in master data by EIN or normalised name (FR-017)."""
    ein = normalize_ein(vendor_vat_id)
    name = normalize_company(vendor_name)
    if not ein and not name:
        return None
    suppliers = list(suppliers)
    if ein:
        for supplier in suppliers:
            if normalize_ein(supplier.vat_id) == ein:
                return supplier
    if name:
        for supplier in suppliers:
            if normalize_company(supplier.name) == name:
                return supplier
    return None


def lexical_match(line_description: str, article_description: str) -> bool:
    """Fallback without the AI service: every word of one side appears in the other.

    Conservative on purpose (FR-007: no suggestion beats a wrong one):
    "Toner cartridge cyan" matches the cyan offers, never "Desk organizer acrylic".
    """
    line_tokens = set(normalize_text(line_description).split())
    article_tokens = set(normalize_text(article_description).split())
    if len(line_tokens) < 2 or len(article_tokens) < 2:
        return False
    return article_tokens <= line_tokens or line_tokens <= article_tokens
