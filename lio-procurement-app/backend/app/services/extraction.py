import json
import logging
import time
import uuid
from collections.abc import Sequence

import openai
from openai import OpenAI
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import CommodityGroup
from app.schemas.booking_rules import ClassificationLineIn
from app.schemas.extraction import (
    ExtractedVendorData,
    ExtractionErrorCode,
    ExtractionResponse,
    LlmQuote,
    QuoteTotals,
)
from app.services import classification, quote_rules

logger = logging.getLogger(__name__)

# Fixed sampling so the same quote gives the same result run to run (as far as
# the service allows).
_TEMPERATURE = 0
_SEED = 7

# Plain-language messages only — technical details go to the server log.
ERROR_MESSAGES: dict[str, str] = {
    "not_configured": (
        "Automatic extraction isn't set up on this server. "
        "Please fill in the form manually or contact your administrator."
    ),
    "service_busy": "The extraction service is busy. Please try again in a minute.",
    "refused": "This document couldn't be processed automatically. Please fill in the form manually.",
    "too_long": "This quote is too long to read automatically. Please fill in the form manually.",
    "unreadable": "We couldn't read this quote automatically. Please fill in the form manually.",
}

SYSTEM_PROMPT = (
    "You extract structured data from US vendor quotes (offers) sent to a buyer. "
    "Read the document exactly as printed; never invent values. When a value is not "
    "printed, return null and list the field in absent_fields."
)


def _build_prompt(pdf_text: str, buyer_names: Sequence[str]) -> str:
    buyers = "\n".join(f"- {name}" for name in buyer_names) or "- (unknown)"
    return f"""Extract the vendor quote below. The text was read from a PDF in layout order;
" | " separates columns that were printed side by side on the same line.

THE BUYER (the recipient of this quote — "Prepared for", "Bill to", "Ship to", addressee):
{buyers}
The buyer is NEVER the vendor.

VENDOR (fill these three in order)
- recipient_name: the company the quote is addressed TO (usually the buyer above).
- vendor_evidence: the exact printed text where you found the issuer's name (e.g. the
  footer line, sender email domain or terms & conditions sentence); never the address block
  of the recipient.
- vendor_name: the company that ISSUED the quote — never recipient_name. The issuer's name is often only in a logo
  (not in the text), so look for it in the footer, "Prepared by", the sender's email/web
  domain, the body text ("your inquiry at X") and the terms & conditions ("The General Terms
  and Conditions of X apply"). Prefer the legal entity name when printed (e.g. "X Interiors,
  Inc." over the brand "X"); otherwise use the brand. Return null only if no issuer name or
  brand appears anywhere.
- vendor_tax_id: only the value printed next to the ISSUER's EIN / Federal Tax ID / Tax ID /
  TIN label. Never a permit, seller's permit, LLC/registration, routing, account, customer,
  quote or phone number, and never the buyer's tax ID. If two different labelled tax IDs are
  printed for the issuer, return null. Return it as printed.

POSITIONS — return EVERY row of the item table, in order, with kind:
- "item": a position that is part of the quoted total.
- "alternative": an option/alternative not included in the total ("Alternative", "Alt.",
  "(Alt.)", "Option", "optional", "instead of item …", rows introduced by "Alternative to the
  preceding item"), or rows whose price is marked as unit price only (e.g. "U.P."). Markers
  such as "(Alt.)" may be printed on the line BELOW the item number or description, and a
  heading like "Alternative: …" makes the following priced row an alternative.
- "heading": a grouping/heading row with neither quantity nor price.
- "promotional": upsell/marketing text that is not part of the offer.
Do not create positions from text outside the item table (page subtotals, "Carried forward",
totals block, notes, terms). Configuration bullets and long descriptions belong to their item.
Shipping/installation printed as a row INSIDE the item table is an "item".
For each position: item_no as printed; description; quantity (decimal allowed, e.g. 13.78);
unit written out in plain English ("ea." -> "pieces", "lic." -> "licenses", "sq ft",
"lump sum"); unit_price (before discount); discount_percent as a positive number (e.g. "-20%"
-> 20); line_total as printed (after discount; null if not printed); price_note for any
marker printed next to the price such as "U.P.".

TOTALS (from the totals block; null when not printed):
- net_total: items subtotal before shipping and tax.
- shipping: shipping/freight printed only in the totals block.
- tax: sum of all sales tax lines.
- fees: other document-level fees (e.g. recycling/eWaste fee).
- grand_total: the final total.
- currency: ISO code, e.g. "USD".

QUOTE REFERENCE: quote_number as printed; quote_date and valid_until as YYYY-MM-DD, only when
printed as dates (do not compute a date from "valid for four weeks").

TITLE: 2-5 words describing the main items being purchased.

Document text:
{pdf_text}"""


def _make_client() -> OpenAI:
    return OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )


def _failure(extraction_id: str, code: ExtractionErrorCode) -> ExtractionResponse:
    return ExtractionResponse(
        success=False, extraction_id=extraction_id, error_code=code, error=ERROR_MESSAGES[code]
    )


def _error_code(exc: Exception) -> ExtractionErrorCode:
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return "not_configured"
    if isinstance(
        exc,
        openai.APITimeoutError
        | openai.APIConnectionError
        | openai.RateLimitError
        | openai.InternalServerError,
    ):
        return "service_busy"
    if isinstance(exc, openai.LengthFinishReasonError):
        return "too_long"
    if isinstance(exc, openai.ContentFilterFinishReasonError):
        return "refused"
    return "unreadable"


def _call_model(client: OpenAI, prompt: str) -> tuple[LlmQuote | None, str | None, str]:
    """Returns (parsed quote, error code, model version)."""
    completion = client.chat.completions.parse(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format=LlmQuote,
        temperature=_TEMPERATURE,
        seed=_SEED,
        max_completion_tokens=8000,
    )
    choice = completion.choices[0]
    model_version = getattr(completion, "model", None) or settings.openai_model
    if choice.message.refusal:
        return None, "refused", model_version
    if choice.finish_reason == "length":
        return None, "too_long", model_version
    if choice.message.parsed is None:
        return None, "unreadable", model_version
    return choice.message.parsed, None, model_version


def build_extraction(
    quote: LlmQuote,
    *,
    buyer_names: Sequence[str],
    commodity_group: CommodityGroup | None = None,
    department: str = "",
) -> tuple[ExtractedVendorData, list[str]]:
    """Apply the deterministic rules to a parsed LLM quote.

    Returns the pre-fill data and the labels of fields the requester must fill in.
    """
    vendor_name = (quote.vendor_name or "").strip()
    if quote_rules.is_buyer(vendor_name, buyer_names):
        logger.info("Vendor matched the buyer's own name; leaving it empty")
        vendor_name = ""
    vat_id = quote_rules.normalize_ein(quote.vendor_tax_id) or ""

    lines, excluded = quote_rules.classify_positions(quote.positions)
    totals = QuoteTotals(
        net_total=quote.net_total,
        shipping=quote.shipping,
        tax=quote.tax,
        fees=quote.fees,
        grand_total=quote.grand_total,
    )

    # Decided by the separate classification stage (booking rules, then system).
    commodity_group_id = commodity_group.id if commodity_group else None

    title = (quote.title or "").strip()
    quote_number = (quote.quote_number or "").strip() or None
    quote_date = quote_rules.normalize_date(quote.quote_date)
    valid_until = quote_rules.normalize_date(quote.valid_until)

    statuses = quote_rules.field_statuses(
        quote,
        title=title,
        vendor_name=vendor_name,
        vat_id=vat_id,
        lines=lines,
        excluded=excluded,
        commodity_group_id=commodity_group_id,
        quote_number=quote_number,
        quote_date=quote_date,
        valid_until=valid_until,
        department=department,
    )

    data = ExtractedVendorData(
        title=title,
        vendor_name=vendor_name,
        vat_id=vat_id,
        department=department,
        quote_number=quote_number,
        quote_date=quote_date,
        valid_until=valid_until,
        currency=(quote.currency or "USD").strip().upper()[:3] or "USD",
        order_lines=lines,
        totals=totals,
        total_cost=quote_rules.compute_total_cost(lines, totals),
        commodity_group_id=commodity_group_id,
        commodity_group_name=commodity_group.name if commodity_group else None,
        excluded_positions=excluded,
        reconciliation=quote_rules.reconcile(lines, totals),
        field_status=statuses,
    )
    return data, quote_rules.missing_field_labels(statuses)


def _classify(
    db: Session, organization_id: uuid.UUID | None, quote: LlmQuote
) -> CommodityGroup | None:
    """Commodity group for the extracted lines: booking rules first, then the system.

    Choosing among 2,000 groups inside the extraction call returned no group at
    all, so classification is its own focused step (spec 003).
    """
    if organization_id is None:
        return None
    lines, _excluded = quote_rules.classify_positions(quote.positions)
    if not lines:
        return None
    result = classification.classify(
        db,
        organization_id,
        [
            ClassificationLineIn(
                description=line.position_description,
                quantity=line.amount,
                unit_price=line.unit_price,
                total_price=line.total_price,
            )
            for line in lines
        ],
    )
    return db.get(CommodityGroup, result.commodity_group_id) if result.commodity_group_id else None


def extract_vendor_data(
    pdf_text: str,
    db: Session,
    *,
    buyer_names: Sequence[str] = (),
    department: str = "",
    organization_id: uuid.UUID | None = None,
    client: OpenAI | None = None,
) -> ExtractionResponse:
    """Extract vendor data, then classify the commodity group from the extracted lines.

    Never raises for extraction problems: failures are returned in the envelope
    with a plain-language message so the UI can always continue.
    """
    extraction_id = str(uuid.uuid4())
    started = time.monotonic()
    log: dict[str, object] = {
        "extraction_id": extraction_id,
        "organization_id": str(organization_id) if organization_id else None,
        "model": settings.openai_model,
    }

    def finish(response: ExtractionResponse) -> ExtractionResponse:
        # One structured line per extraction for support — never the document text.
        log["duration_ms"] = round((time.monotonic() - started) * 1000)
        log["outcome"] = "success" if response.success else response.error_code
        if response.data is not None:
            log["line_count"] = len(response.data.order_lines)
            log["excluded_count"] = len(response.data.excluded_positions)
            log["reconciliation_findings"] = len(response.data.reconciliation)
            log["field_status"] = response.data.field_status
        logger.info("extraction %s", json.dumps(log, default=str))
        return response

    if not pdf_text or not pdf_text.strip():
        return finish(_failure(extraction_id, "unreadable"))
    if client is None and not settings.openai_api_key:
        return finish(_failure(extraction_id, "not_configured"))

    try:
        quote, error_code, model_version = _call_model(
            client or _make_client(), _build_prompt(pdf_text, buyer_names)
        )
    except (openai.OpenAIError, ValidationError) as exc:
        logger.exception("Extraction %s failed", extraction_id)
        return finish(_failure(extraction_id, _error_code(exc)))
    log["model"] = model_version
    if error_code is not None:
        return finish(_failure(extraction_id, error_code))

    data, missing = build_extraction(
        quote,
        buyer_names=buyer_names,
        commodity_group=_classify(db, organization_id, quote),
        department=department,
    )
    return finish(
        ExtractionResponse(
            success=True,
            extraction_id=extraction_id,
            data=data,
            missing_fields=missing or None,
        )
    )
