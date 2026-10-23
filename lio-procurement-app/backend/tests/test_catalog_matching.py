"""Catalog suggestion rules — pure functions; figures from spec 002 Appendix A."""
import uuid

import pytest

from app.schemas.catalog import SuggestionLineIn
from app.services import catalog_matching as rules
from app.services.catalog_matching import CatalogArticle, SupplierRef

HARBORVIEW, REDWOOD, AURORA, MONTCLAIR, BEACON = (uuid.uuid4() for _ in range(5))


def _article(number, description, price, unit="piece", supplier=None, min_qty=1.0):
    return CatalogArticle(
        id=uuid.uuid4(), article_number=number, description=description,
        supplier_id=supplier or uuid.uuid4(), supplier_name=f"Supplier of {number}",
        unit_price=price, unit=unit, currency="USD", min_quantity=min_qty,
    )


def _line(description="x", unit="pieces", quantity=1, unit_price=None, total=None, discount=0):
    return SuggestionLineIn(
        key="0", description=description, unit=unit, quantity=quantity, unit_price=unit_price,
        total_price=total, discount_percent=discount,
    )


def _suggest(article, line, relevance=0.5, vendor=None):
    return rules.build_suggestion(article, line, relevance=relevance, vendor_supplier_id=vendor)


HAR = _article("HAR-00172", "Custom moss wall, preserved reindeer moss", 44.59, "sq ft", HARBORVIEW)
RED = _article("RED-00196", "Framed preserved moss panel with logo", 320.0, "piece", REDWOOD)
AUR = _article("AUR-00413", 'Business laptop 13" ultralight', 1650.0, "piece", AURORA, 10)
MON = _article("MON-00922", "Toner cartridge cyan", 95.0, "piece", MONTCLAIR, 10)
BEA = _article("BEA-01877", "Toner cartridge cyan", 117.0, "piece", BEACON, 5)


@pytest.mark.parametrize(
    "raw, unit",
    [("pieces", "piece"), ("ea.", "piece"), ("EA", "piece"), ("Sq Ft", "sq ft"),
     ("square feet", "sq ft"), ("lin ft", "ft"), ("Hours", "hour"), ("lump sum", "lump sum")],
)
def test_normalize_unit(raw, unit):
    assert rules.normalize_unit(raw) == unit


# --- SC-004: saving / extra-cost figures to the cent --------------------------------


def test_r1_custom_moss_saving():
    s = _suggest(HAR, _line(unit="sq ft", quantity=13.78, unit_price=52.0, total=716.56))
    assert (s.comparable, s.unit_difference, s.line_effect) == (True, -7.41, -102.11)


def test_r2_compares_the_discounted_net_price_and_flags_unit_mismatch():
    line = _line(quantity=1, unit_price=894.08, discount=20, total=715.26)
    red = _suggest(RED, line)
    assert red.line_effect == -395.26  # 320.00 vs 715.26 net, not vs 894.08
    har = _suggest(HAR, line)
    assert (har.comparable, har.line_effect) == (False, None)  # piece vs sq ft


def test_r3_and_r5_more_expensive_is_never_a_saving():
    assert _suggest(RED, _line(unit_price=1560.0, total=1560.0)).line_effect == -1240.0
    macbook = _suggest(AUR, _line(unit_price=1409.06, total=1409.06))
    assert macbook.line_effect == 240.94 and macbook.unit_difference == 240.94
    assert rules.best_cheaper_alternative([macbook]) is None


def test_r9_saving_and_minimum_order_quantity():
    s = _suggest(MON, _line(quantity=5, unit_price=150.0, total=750.0))
    assert (s.line_effect, s.below_min_quantity) == (-275.0, True)
    assert not _suggest(BEA, _line(quantity=5, unit_price=150.0)).below_min_quantity


def test_no_price_or_other_currency_is_not_compared():
    assert not _suggest(MON, _line(quantity=5)).comparable  # R8: no current price
    euro = _line(quantity=1, unit_price=100.0)
    euro.currency = "EUR"
    assert not _suggest(MON, euro).comparable


# --- Ranking -------------------------------------------------------------------------


def test_identical_items_rank_cheapest_first_and_relevance_first_otherwise():
    line = _line("Toner cartridge cyan", quantity=5)
    del_ = _article("DEL-00890", "Toner cartridge cyan", 139.0)
    ranked = rules.rank(
        [_suggest(a, line, relevance=0.99) for a in (del_, BEA, MON)]
        + [_suggest(_article("X-1", "Toner black", 50.0), line, relevance=0.7)],
        limit=3,
    )
    assert [s.article_number for s in ranked] == ["MON-00922", "BEA-01877", "DEL-00890"]

    moss = _line("Moss Art Panel", quantity=1, unit_price=715.26)
    ranked = rules.rank([_suggest(HAR, moss, 0.58), _suggest(RED, moss, 0.64)], limit=3)
    assert [s.article_number for s in ranked] == ["RED-00196", "HAR-00172"]


def test_contracted_supplier_ranks_first_and_overcharge_is_flagged():
    line = _line("Toner cartridge cyan", quantity=10, unit_price=120.0, total=1200.0)
    suggestions = [_suggest(BEA, line, 0.99), _suggest(MON, line, 0.99, vendor=MONTCLAIR)]
    ranked = rules.rank(suggestions, limit=3)
    assert ranked[0].article_number == "MON-00922" and ranked[0].from_vendor
    check = rules.agreement_check(suggestions)
    assert (check.article_number, check.negotiated_price, check.difference) == (
        "MON-00922", 95.0, 25.0,
    )


def test_no_agreement_check_when_vendor_is_cheaper_than_its_catalog():
    line = _line("Toner cartridge cyan", quantity=10, unit_price=90.0)
    assert rules.agreement_check([_suggest(MON, line, vendor=MONTCLAIR)]) is None


def test_best_cheaper_alternative_picks_the_cheapest_comparable():
    line = _line("Toner cartridge cyan", quantity=5, unit_price=150.0)
    best = rules.best_cheaper_alternative([_suggest(BEA, line), _suggest(MON, line)])
    assert (best.article_number, -best.line_effect) == ("MON-00922", 275.0)


# --- Contracted supplier recognition (FR-017) ------------------------------------------


SUPPLIERS = [
    SupplierRef(MONTCLAIR, "Montclair Supply Corp.", "10-0046227"),
    SupplierRef(uuid.uuid4(), "Montclair Systems LLC", "10-0047038"),
]


@pytest.mark.parametrize(
    "name, ein, expected",
    [
        ("Montclair Supply Corp", None, MONTCLAIR),
        ("MONTCLAIR SUPPLY CORPORATION", "", MONTCLAIR),
        ("Some trading name", "10 0046227", MONTCLAIR),
        ("Montclair", None, None),
        ("Hollis Greenscapes", "94-1985704", None),
        (None, None, None),
    ],
)
def test_match_supplier(name, ein, expected):
    match = rules.match_supplier(name, ein, SUPPLIERS)
    assert (match.id if match else None) == expected


# --- Lexical fallback (FR-027) -----------------------------------------------------------


@pytest.mark.parametrize(
    "line, article, expected",
    [
        ("Toner cartridge cyan", "Toner cartridge cyan", True),
        ("HP toner cartridge cyan 202A", "Toner cartridge cyan", True),
        ("Toner cartridge cyan", "Toner cartridge black, high-yield", False),
        ("Logo acrylic white with standoffs", "Desk organizer acrylic", False),
        ("Grinding machine HW-GS 450", "CNC machining turning", False),
        ("Toner", "Toner cartridge cyan", False),  # too short to be safe
    ],
)
def test_lexical_match(line, article, expected):
    assert rules.lexical_match(line, article) is expected
