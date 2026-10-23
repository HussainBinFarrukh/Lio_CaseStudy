"""Extraction service with a stubbed OpenAI client — no network, no API key."""
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.schemas.extraction import LlmQuote
from app.seed import seed_commodity_groups
from app.services.extraction import ERROR_MESSAGES, extract_vendor_data

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = json.loads((FIXTURES / "reference_quotes.json").read_text(encoding="utf-8"))
PAYLOADS = json.loads((FIXTURES / "llm_payloads.json").read_text(encoding="utf-8"))
BUYERS = REFERENCE["buyer_names"]

_engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
Base.metadata.create_all(_engine)
_Session = sessionmaker(bind=_engine, expire_on_commit=False)
with _Session() as _s:
    seed_commodity_groups(_s)
    _s.commit()


class StubClient:
    """Mimics ``client.chat.completions.parse`` returning a fixed outcome."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def completion(parsed=None, refusal=None, finish_reason="stop"):
    message = SimpleNamespace(parsed=parsed, refusal=refusal)
    return SimpleNamespace(
        model="gpt-test-2024", choices=[SimpleNamespace(finish_reason=finish_reason, message=message)]
    )


def run(outcome, text="Quote 123", **kwargs):
    client = StubClient(outcome)
    with _Session() as db:
        response = extract_vendor_data(
            text, db, buyer_names=BUYERS, client=client, **kwargs
        )
    return response, client


# --- US1–US8 on the five reference quotes ------------------------------------


@pytest.mark.parametrize("filename", sorted(k for k in PAYLOADS if not k.startswith("_")))
def test_reference_quote_matches_ground_truth(filename):
    expected = REFERENCE["quotes"][filename]
    response, _ = run(completion(LlmQuote.model_validate(PAYLOADS[filename])))

    assert response.success, response.error
    data = response.data
    assert data.vendor_name in expected["vendor"]
    assert data.vat_id == expected["vat_id"]
    assert [line.total_price for line in data.order_lines] == expected["line_totals"]
    assert [
        e.item_no for e in data.excluded_positions if e.reason == "alternative"
    ] == expected["alternatives"]
    assert data.totals.net_total == expected["net_total"]
    assert data.total_cost == expected["grand_total"]  # total cost = grand total
    assert data.reconciliation == []
    assert (data.quote_number, data.quote_date, data.valid_until) == (
        expected["quote_number"], expected["quote_date"], expected["valid_until"]
    )
    # A legitimately absent tax ID is informational, not a "please fill in" warning.
    if not expected["vat_id"]:
        assert data.field_status["vatId"] == "not_in_document"
    assert "Tax ID" not in (response.missing_fields or [])
    assert response.extraction_id


def test_buyer_returned_as_vendor_is_cleared_and_flagged():
    payload = dict(PAYLOADS["QuoteA0492_23.Pdf"], vendor_name="Lio Technologies, Inc.")
    response, _ = run(completion(LlmQuote.model_validate(payload)))
    assert response.success
    assert response.data.vendor_name == ""
    assert response.data.field_status["vendorName"] == "could_not_extract"
    assert "Vendor Name" in response.missing_fields


def test_prompt_names_the_buyer_and_department_comes_from_profile():
    payload = PAYLOADS["Quote_Hartwell_Cleveland_ACME_Grinding_Machine.pdf"]
    response, client = run(
        completion(LlmQuote.model_validate(payload)), department="Engineering"
    )
    prompt = client.calls[0]["messages"][1]["content"]
    assert "- Lio Technologies, Inc." in prompt and "- ACME Corp" in prompt
    assert client.calls[0]["response_format"] is LlmQuote
    assert client.calls[0]["temperature"] == 0
    assert response.data.department == "Engineering"


# --- US1: failures never leak technical text -----------------------------------

_REQUEST = httpx.Request("POST", "https://api.openai.example/v1/chat/completions")


@pytest.mark.parametrize(
    "outcome, code",
    [
        (openai.APITimeoutError(request=_REQUEST), "service_busy"),
        (openai.APIConnectionError(message="conn reset by peer", request=_REQUEST), "service_busy"),
        (
            openai.RateLimitError(
                "Rate limit reached for gpt-4o-mini", response=httpx.Response(429, request=_REQUEST),
                body=None,
            ),
            "service_busy",
        ),
        (
            openai.InternalServerError(
                "upstream 502", response=httpx.Response(502, request=_REQUEST), body=None
            ),
            "service_busy",
        ),
        (
            openai.AuthenticationError(
                "Incorrect API key provided: sk-…", response=httpx.Response(401, request=_REQUEST),
                body=None,
            ),
            "not_configured",
        ),
        (completion(refusal="I can't help with that."), "refused"),
        (completion(finish_reason="length"), "too_long"),
        (completion(parsed=None), "unreadable"),
        (ValueError("unexpected"), None),  # non-API bugs are not swallowed
    ],
)
def test_failures_map_to_plain_language(outcome, code):
    if code is None:
        with pytest.raises(ValueError):
            run(outcome)
        return
    response, _ = run(outcome)
    assert response.success is False
    assert response.error_code == code
    assert response.error == ERROR_MESSAGES[code]
    for technical in ("sk-", "Rate limit", "502", "conn reset", "Traceback", "Error"):
        assert technical not in response.error


def test_malformed_model_output_is_unreadable_not_a_crash():
    try:
        LlmQuote.model_validate({"positions": "nope"})
    except Exception as exc:  # noqa: BLE001 — the real ValidationError instance
        validation_error = exc
    response, _ = run(validation_error)
    assert (response.success, response.error_code) == (False, "unreadable")


def test_empty_text_and_missing_key(monkeypatch):
    monkeypatch.setattr("app.services.extraction.settings.openai_api_key", None)
    with _Session() as db:
        empty = extract_vendor_data("   ", db, buyer_names=BUYERS)
        no_key = extract_vendor_data("Quote 1", db, buyer_names=BUYERS)
    assert empty.error_code == "unreadable"
    assert no_key.error_code == "not_configured"
    assert "OPENAI" not in no_key.error


def test_response_uses_camel_case_wire_format():
    response, _ = run(completion(LlmQuote.model_validate(PAYLOADS["QT-4120-Cust-14918.pdf"])))
    wire = response.model_dump(by_alias=True)
    assert {"extractionId", "missingFields", "errorCode"} <= wire.keys()
    data = wire["data"]
    assert data["orderLines"][0]["discountPercent"] == 20
    assert data["totals"]["grandTotal"] == 1686.14
    assert data["excludedPositions"][-1]["itemNo"] == "5"
    assert data["fieldStatus"]["validUntil"] == "extracted"
