"""Deterministic post-processing of an LLM quote extraction.

The model reads the document; these rules decide what is trusted. Everything
here is pure (no I/O) so it can be tested without the extraction service.
"""
import re
from collections.abc import Iterable
from datetime import date

from app.schemas.extraction import (
    ExcludedPosition,
    FieldStatus,
    LlmPosition,
    LlmQuote,
    OrderLineData,
    QuoteTotals,
    ReconciliationFinding,
)

# Amounts are compared to the cent, allowing for rounding on the printed quote.
TOLERANCE = 0.02

# ---------------------------------------------------------------------------
# Buyer guard
# ---------------------------------------------------------------------------

_LEGAL_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co",
    "company", "gmbh", "ag", "plc", "lp", "llp",
}


def normalize_company(name: str | None) -> str:
    """Comparable form of a company name: casefolded, no punctuation or legal suffix."""
    if not name:
        return ""
    words = re.sub(r"[^\w\s]", " ", name.casefold().replace("&", " and ")).split()
    return " ".join(w for w in words if w not in _LEGAL_SUFFIXES)


def is_buyer(vendor_name: str | None, buyer_names: Iterable[str]) -> bool:
    """True if the vendor is (a variant of) one of the buyer's own names."""
    vendor = normalize_company(vendor_name)
    if not vendor:
        return False
    for buyer_name in buyer_names:
        buyer = normalize_company(buyer_name)
        if not buyer:
            continue
        # Whole-word containment either way: "Lio Technologies" vs "Lio Technologies, Inc.".
        if f" {buyer} " in f" {vendor} " or f" {vendor} " in f" {buyer} ":
            return True
    return False


# ---------------------------------------------------------------------------
# Tax ID
# ---------------------------------------------------------------------------


def normalize_ein(raw: str | None) -> str | None:
    """US EIN as ``XX-XXXXXXX``; anything that isn't exactly 9 digits is rejected."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 9:
        return None
    return f"{digits[:2]}-{digits[2:]}"


# ---------------------------------------------------------------------------
# Positions: order lines vs. excluded rows
# ---------------------------------------------------------------------------

# "Alternative: …", "Alt.", "(Alt.)", "Option", "optional", "instead of item 3"
_ALTERNATIVE_TEXT = re.compile(
    r"^\s*(alt\.|alternative\b|option(al)?\b)|\(\s*alt\.?\s*\)|\binstead of item\b",
    re.IGNORECASE,
)
# "U.P." = unit price only — the amount is not part of the quoted total.
_UNIT_PRICE_ONLY = re.compile(r"\bU\.?\s?P\.?(?!\w)", re.IGNORECASE)


def _round(value: float) -> float:
    return round(value + 0.0, 2)


def _exclusion_reason(position: LlmPosition) -> str | None:
    has_price = position.unit_price is not None or position.line_total is not None
    if position.kind == "promotional":
        return "promotional"
    if position.quantity is None and not has_price:
        return "heading"
    if position.kind == "alternative":
        return "alternative"
    if position.price_note and _UNIT_PRICE_ONLY.search(position.price_note):
        return "alternative"
    if position.unit_price is not None and position.line_total is None and (
        position.price_note or position.kind != "item"
    ):
        return "alternative"
    for text in (position.item_no, position.description):
        if text and _ALTERNATIVE_TEXT.search(text):
            return "alternative"
    if position.kind == "heading":
        return "heading"
    return None


def _to_order_line(position: LlmPosition) -> OrderLineData:
    quantity = position.quantity if position.quantity is not None else 1.0
    discount = position.discount_percent or 0.0
    unit_price = position.unit_price
    if unit_price is None:
        # Only a line total is printed: derive the undiscounted unit price.
        factor = quantity * (1 - discount / 100)
        unit_price = _round(position.line_total / factor) if factor else position.line_total
    line_total = position.line_total
    if line_total is None:
        line_total = _round(quantity * unit_price * (1 - discount / 100))
    return OrderLineData(
        position_description=position.description.strip(),
        unit_price=unit_price,
        amount=quantity,
        unit=(position.unit or "").strip(),
        discount_percent=discount,
        total_price=line_total,
    )


def classify_positions(
    positions: Iterable[LlmPosition],
) -> tuple[list[OrderLineData], list[ExcludedPosition]]:
    """Split item-table rows into billable order lines and excluded rows."""
    lines: list[OrderLineData] = []
    excluded: list[ExcludedPosition] = []
    # A heading such as "Alternative: vertical logo" introduces the next priced
    # row as an alternative even when that row's own "(Alt.)" marker was lost.
    after_alternative_heading = False
    for position in positions:
        reason = _exclusion_reason(position)
        if reason is None and after_alternative_heading:
            reason = "alternative"
        if reason == "heading":
            after_alternative_heading = bool(
                _ALTERNATIVE_TEXT.search(position.description or "")
            )
        else:
            after_alternative_heading = False
        if reason is None:
            lines.append(_to_order_line(position))
        else:
            excluded.append(
                ExcludedPosition(
                    item_no=position.item_no,
                    description=position.description.strip(),
                    amount=(
                        position.line_total
                        if position.line_total is not None
                        else position.unit_price
                    ),
                    reason=reason,
                )
            )
    return lines, excluded


def recalculate_line_total(amount: float, unit_price: float, discount_percent: float) -> float:
    return _round(amount * unit_price * (1 - discount_percent / 100))


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------


def compute_total_cost(lines: list[OrderLineData], totals: QuoteTotals) -> float:
    """Request total cost = grand total (net + shipping + tax + fees)."""
    if totals.grand_total is not None:
        return _round(totals.grand_total)
    net = totals.net_total
    if net is None:
        net = sum(line.total_price for line in lines)
    return _round(net + (totals.shipping or 0) + (totals.tax or 0) + (totals.fees or 0))


def reconcile(lines: list[OrderLineData], totals: QuoteTotals) -> list[ReconciliationFinding]:
    """Cross-check lines and totals; every mismatch beyond 2 cents is reported."""
    findings: list[ReconciliationFinding] = []
    for index, line in enumerate(lines):
        expected = recalculate_line_total(line.amount, line.unit_price, line.discount_percent)
        if abs(expected - line.total_price) > TOLERANCE:
            findings.append(
                ReconciliationFinding(
                    scope="line", line_index=index, expected=expected, extracted=line.total_price
                )
            )

    if totals.net_total is not None and lines:
        lines_sum = _round(sum(line.total_price for line in lines))
        # Shipping may be a table item (already in the lines) or only in the totals block.
        candidates = [lines_sum]
        if totals.shipping:
            candidates.append(_round(lines_sum + totals.shipping))
        if all(abs(c - totals.net_total) > TOLERANCE for c in candidates):
            findings.append(
                ReconciliationFinding(
                    scope="net_total", expected=lines_sum, extracted=totals.net_total
                )
            )

    if totals.grand_total is not None and totals.net_total is not None:
        expected = _round(
            totals.net_total + (totals.shipping or 0) + (totals.tax or 0) + (totals.fees or 0)
        )
        if abs(expected - totals.grand_total) > TOLERANCE:
            findings.append(
                ReconciliationFinding(
                    scope="grand_total", expected=expected, extracted=totals.grand_total
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def normalize_date(raw: str | None) -> str | None:
    """ISO ``YYYY-MM-DD`` or ``None``; also accepts US ``MM/DD/YY(YY)``."""
    if not raw:
        return None
    text = raw.strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        pass
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", text)
    if match:
        month, day, year = (int(g) for g in match.groups())
        year = year + 2000 if year < 100 else year
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Field status (what to tell the requester about each field)
# ---------------------------------------------------------------------------

FIELD_LABELS = {
    "title": "Title/Short Description",
    "vendorName": "Vendor Name",
    "vatId": "Tax ID",
    "orderLines": "Order Lines",
    "totalCost": "Total Cost",
    "commodityGroup": "Commodity Group",
    "quoteNumber": "Quote Number",
    "quoteDate": "Quote Date",
    "validUntil": "Valid Until",
}


def _status(present: bool, absent: bool) -> FieldStatus:
    if present:
        return "extracted"
    return "not_in_document" if absent else "could_not_extract"


def field_statuses(
    quote: LlmQuote,
    *,
    title: str,
    vendor_name: str,
    vat_id: str,
    lines: list[OrderLineData],
    excluded: list[ExcludedPosition],
    commodity_group_id: int | None,
    quote_number: str | None,
    quote_date: str | None,
    valid_until: str | None,
    department: str,
) -> dict[str, FieldStatus]:
    """Per-field status. A value of 0 counts as present; ``None``/"" do not."""
    absent = set(quote.absent_fields)
    has_total = (
        quote.grand_total is not None or quote.net_total is not None or bool(lines)
    )
    statuses: dict[str, FieldStatus] = {
        "title": _status(bool(title), False),
        # A vendor/tax ID cleared by our rules was in the document: never "absent".
        "vendorName": _status(
            bool(vendor_name), "vendor_name" in absent and not quote.vendor_name
        ),
        "vatId": _status(bool(vat_id), "vendor_tax_id" in absent and not quote.vendor_tax_id),
        # Rows were read but none is billable: nothing to buy in the document.
        "orderLines": _status(bool(lines), bool(excluded)),
        "totalCost": _status(has_total, False),
        "commodityGroup": _status(commodity_group_id is not None, False),
        "quoteNumber": _status(bool(quote_number), "quote_number" in absent),
        "quoteDate": _status(bool(quote_date), "quote_date" in absent),
        "validUntil": _status(bool(valid_until), "valid_until" in absent),
    }
    if department:
        statuses["department"] = "extracted"
    return statuses


def missing_field_labels(statuses: dict[str, FieldStatus]) -> list[str]:
    """Labels of fields the requester must fill in (``could_not_extract`` only)."""
    return [
        FIELD_LABELS[field]
        for field, status in statuses.items()
        if status == "could_not_extract" and field in FIELD_LABELS
    ]
