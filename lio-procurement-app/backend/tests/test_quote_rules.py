"""Deterministic extraction rules — pure functions, no network, no database."""
import pytest

from app.schemas.extraction import LlmPosition, LlmQuote, OrderLineData, QuoteTotals
from app.services import quote_rules
from app.services.numbers import parse_amount, parse_percent

BUYERS = ["Acme Corp", "ACME Corp", "Lio Technologies, Inc.", "askLio"]


def _position(**overrides) -> LlmPosition:
    fields = {
        "item_no": None, "kind": "item", "description": "Thing", "quantity": 1, "unit": "pieces",
        "unit_price": 10.0, "discount_percent": None, "line_total": 10.0, "price_note": None,
    }
    fields.update(overrides)
    return LlmPosition(**fields)


def _quote(**overrides) -> LlmQuote:
    fields = {
        "title": "T", "recipient_name": None, "vendor_evidence": None, "vendor_name": "V",
        "vendor_tax_id": None, "quote_number": None, "quote_date": None,
        "valid_until": None, "currency": "USD", "positions": [], "net_total": None, "shipping": None,
        "tax": None, "fees": None, "grand_total": None, "commodity_group_id": None, "absent_fields": [],
    }
    fields.update(overrides)
    return LlmQuote(**fields)


# --- FR-002: input tolerance -------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("$1,409.06", 1409.06),
        ("1,234.56", 1234.56),
        ("USD 2,042.15", 2042.15),
        (715.26, 715.26),
        (3, 3.0),
        ("-20.00", -20.0),
        (None, None),
        ("", None),
        ("n/a", None),
        (True, None),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_parse_percent_is_sign_insensitive():
    assert parse_percent("-20.00%") == 20.0
    assert parse_percent(None) is None


def test_llm_schema_tolerates_string_amounts_and_nulls():
    position = LlmPosition(
        item_no="1", kind="item", description="Panel", quantity="1.00", unit=None,
        unit_price="$894.08", discount_percent="-20.00%", line_total="715.26", price_note=None,
    )
    assert (position.quantity, position.unit_price, position.discount_percent) == (1, 894.08, 20)
    quote = _quote(grand_total="$1,686.14", tax=None)
    assert quote.grand_total == 1686.14 and quote.tax is None


# --- US2: buyer guard and tax ID ----------------------------------------------


@pytest.mark.parametrize(
    "vendor",
    ["Lio Technologies, Inc.", "LIO TECHNOLOGIES INC", "Lio Technologies", "ACME Corp.", "askLio"],
)
def test_buyer_names_are_never_the_vendor(vendor):
    assert quote_rules.is_buyer(vendor, BUYERS)


@pytest.mark.parametrize(
    "vendor", ["Apple Inc.", "Hollis Greenscapes", "Hartwell Industrial Tools, Inc.", "", None]
)
def test_real_vendors_pass_the_buyer_guard(vendor):
    assert not quote_rules.is_buyer(vendor, BUYERS)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("85-3252405", "85-3252405"),
        ("94 1985704", "94-1985704"),
        ("941985704", "94-1985704"),
        ("102-7365501", None),  # Greenmantle seller's permit (10 digits)
        ("121145307 0013", None),  # routing + account
        ("12-345678", None),
        (None, None),
    ],
)
def test_normalize_ein(raw, expected):
    assert quote_rules.normalize_ein(raw) == expected


# --- US3: positions -------------------------------------------------------------


def test_headings_alternatives_and_promotions_are_excluded():
    positions = [
        _position(item_no="1", kind="heading", description="Moss art panel", quantity=None,
                  unit_price=None, line_total=None),
        _position(item_no="1.1", description="Panel", unit_price=1560, line_total=1560),
        _position(item_no="1.1a", description="Ball moss only", unit_price=2090,
                  line_total=None, price_note="U.P."),
        _position(item_no="1.1b", kind="alternative", unit_price=1830, line_total=None),
        _position(item_no="5", description="(Alt.) vertical logo", unit_price=430, line_total=430),
        _position(item_no="6", description="Alternative: wall mount", unit_price=10, line_total=10),
        _position(item_no="7", description="Instead of item 3: matte finish", unit_price=5,
                  line_total=5),
        _position(item_no=None, kind="promotional", description="Moss Duo just $79",
                  quantity=None, unit_price=79, line_total=None),
        _position(item_no="1.2", description="Transport", unit_price=320, line_total=320),
    ]
    lines, excluded = quote_rules.classify_positions(positions)

    assert [line.total_price for line in lines] == [1560, 320]
    assert [(e.item_no, e.reason) for e in excluded] == [
        ("1", "heading"),
        ("1.1a", "alternative"),
        ("1.1b", "alternative"),
        ("5", "alternative"),
        ("6", "alternative"),
        ("7", "alternative"),
        (None, "promotional"),
    ]
    assert excluded[1].amount == 2090


def test_row_after_alternative_heading_is_an_alternative():
    # Seen live on Greenmantle: the "(Alt.)" marker sits on the line below item 5,
    # so the model returned it as a plain item after the "Alternative:" heading.
    lines, excluded = quote_rules.classify_positions(
        [
            _position(item_no="1", kind="heading", description="Moss Art Panel 63 x 31.5 in",
                      quantity=None, unit_price=None, line_total=None),
            _position(item_no="2", description="Moss Art Panel 63 x 31.5 in", unit_price=715.26,
                      line_total=715.26),
            _position(item_no="3", description="Logo horizontal", unit_price=622, line_total=622),
            _position(item_no="4", kind="heading", description="Alternative: vertical logo",
                      quantity=None, unit_price=None, line_total=None),
            _position(item_no="5", description="Logo vertical", unit_price=430, line_total=430),
        ]
    )
    assert [line.total_price for line in lines] == [715.26, 622]
    assert [(e.item_no, e.reason) for e in excluded] == [
        ("1", "heading"), ("4", "heading"), ("5", "alternative"),
    ]


def test_free_position_and_missing_quantity_are_kept():
    lines, excluded = quote_rules.classify_positions(
        [
            _position(description="Free sample", unit_price=0, line_total=0),
            _position(description="Lump sum", quantity=None, unit_price=None, line_total=2000),
        ]
    )
    assert not excluded
    assert lines[0].total_price == 0
    assert (lines[1].amount, lines[1].unit_price, lines[1].total_price) == (1, 2000, 2000)


def test_discount_is_kept_on_the_line():
    lines, _ = quote_rules.classify_positions(
        [_position(unit_price=894.08, discount_percent=20, line_total=715.26)]
    )
    assert (lines[0].unit_price, lines[0].discount_percent, lines[0].total_price) == (
        894.08, 20, 715.26,
    )
    # Editing quantity keeps the discount (US4 scenario 2).
    assert quote_rules.recalculate_line_total(2, 894.08, 20) == 1430.53


# --- US4: totals ------------------------------------------------------------------


def _line(total: float, unit_price: float | None = None, amount: float = 1, discount=0):
    return OrderLineData(
        position_description="x", unit_price=unit_price if unit_price is not None else total,
        amount=amount, unit="pieces", discount_percent=discount, total_price=total,
    )


def test_total_cost_is_the_grand_total():
    totals = QuoteTotals(net_total=1880, tax=162.15, grand_total=2042.15)
    assert quote_rules.compute_total_cost([_line(1560), _line(320)], totals) == 2042.15


def test_total_cost_without_printed_grand_total_adds_up_the_parts():
    totals = QuoteTotals(net_total=1337.26, shipping=215, tax=133.88)
    assert quote_rules.compute_total_cost([], totals) == 1686.14
    assert quote_rules.compute_total_cost([_line(100), _line(50)], QuoteTotals(tax=10)) == 160


# --- US5: reconciliation ------------------------------------------------------------


def test_reference_totals_reconcile():
    # Greenmantle: shipping only in the totals block; net excludes it.
    lines = [_line(715.26, unit_price=894.08, discount=20), _line(622)]
    totals = QuoteTotals(
        net_total=1337.26, shipping=215, tax=133.88, grand_total=1686.14
    )
    assert quote_rules.reconcile(lines, totals) == []
    # Hollis: shipping is a table line.
    assert quote_rules.reconcile(
        [_line(1560), _line(320)], QuoteTotals(net_total=1880, tax=162.15, grand_total=2042.15)
    ) == []


def test_mismatches_are_reported_precisely():
    lines = [_line(100, unit_price=60, amount=2), _line(50)]
    totals = QuoteTotals(net_total=200, tax=10, grand_total=999)
    findings = quote_rules.reconcile(lines, totals)
    assert [(f.scope, f.line_index, f.expected, f.extracted) for f in findings] == [
        ("line", 0, 120, 100),
        ("net_total", None, 150, 200),
        ("grand_total", None, 210, 999),
    ]


def test_two_cent_rounding_is_tolerated():
    lines = [_line(120.49, unit_price=7.65, amount=15.75)]
    assert quote_rules.reconcile(lines, QuoteTotals(net_total=120.5)) == []


# --- US6: field status ---------------------------------------------------------------


def _statuses(quote: LlmQuote, **overrides):
    fields = {
        "title": "T", "vendor_name": "V", "vat_id": "", "lines": [_line(10)], "excluded": [],
        "commodity_group_id": 1, "quote_number": None, "quote_date": None, "valid_until": None,
        "department": "",
    }
    fields.update(overrides)
    return quote_rules.field_statuses(quote, **fields)


def test_tax_id_not_in_document_is_informational():
    statuses = _statuses(_quote(absent_fields=["vendor_tax_id", "valid_until"]))
    assert statuses["vatId"] == "not_in_document"
    assert statuses["validUntil"] == "not_in_document"
    assert "Tax ID" not in quote_rules.missing_field_labels(statuses)


def test_cleared_vendor_is_could_not_extract():
    # The model read "Lio Technologies, Inc." (present) but the buyer guard cleared it.
    statuses = _statuses(
        _quote(vendor_name="Lio Technologies, Inc.", absent_fields=["vendor_name"]),
        vendor_name="",
    )
    assert statuses["vendorName"] == "could_not_extract"
    assert "Vendor Name" in quote_rules.missing_field_labels(statuses)


def test_zero_total_is_not_missing():
    statuses = _statuses(_quote(grand_total=0), lines=[_line(0)])
    assert statuses["totalCost"] == "extracted"
    assert statuses["orderLines"] == "extracted"


def test_all_rows_excluded_is_reported_as_no_billable_lines():
    statuses = _statuses(_quote(), lines=[], excluded=["x"])
    assert statuses["orderLines"] == "not_in_document"


@pytest.mark.parametrize(
    "raw, expected",
    [("2023-11-28", "2023-11-28"), ("01/27/24", "2024-01-27"), ("12/12/2023", "2023-12-12"),
     ("13/40/2023", None), ("next month", None), (None, None)],
)
def test_normalize_date(raw, expected):
    assert quote_rules.normalize_date(raw) == expected
