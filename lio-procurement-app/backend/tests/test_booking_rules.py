"""Booking-rule engine — deterministic, no AI; spec 003 Appendix A."""
import json
import uuid
from pathlib import Path

import pytest

from app.seed import ORG_BOOKING_RULES
from app.services import booking_rules as engine

REFERENCE = json.loads(
    (Path(__file__).parent / "fixtures" / "booking_reference.json").read_text(encoding="utf-8")
)

ACME_RULES = [
    engine.Rule(
        id=uuid.uuid4(),
        name=r["name"],
        description=r["description"],
        include_terms=tuple(r["include_terms"]),
        exclude_terms=tuple(r["exclude_terms"]),
        target_group_id=r["target_commodity_group_id"],
        max_annual_amount=r["max_annual_amount"],
    )
    for r in ORG_BOOKING_RULES["acme"]
]


def _lines(raw):
    return [
        engine.Line(
            description=line["description"],
            quantity=line.get("quantity", 1),
            unit_price=line.get("unitPrice"),
            total_price=line.get("totalPrice"),
        )
        for line in raw
    ]


@pytest.mark.parametrize("scenario", REFERENCE["scenarios"], ids=lambda s: s["id"])
def test_reference_scenarios(scenario):
    outcome = engine.evaluate(ACME_RULES, _lines(scenario["lines"]))
    assert (outcome.rule.name if outcome.rule else None) == scenario["acme_rule"]
    assert outcome.mandated_group_id == scenario["acme_group"]
    if "deciding_line" in scenario:
        assert outcome.deciding_index == scenario["deciding_line"]
    assert outcome.split_advice == scenario.get("split_advice", False)


@pytest.mark.parametrize(
    "rule, text",
    [(rule, text) for rule, texts in REFERENCE["variants"].items() for text in texts],
)
def test_wording_variants_match_their_rule(rule, text):
    outcome = engine.evaluate(ACME_RULES, [engine.Line(text, 1, 10.0, 10.0)])
    assert outcome.rule is not None and outcome.rule.name == rule


@pytest.mark.parametrize("text", REFERENCE["never_rules"])
def test_neighbouring_items_never_match(text):
    assert engine.evaluate(ACME_RULES, [engine.Line(text, 1, 10.0, 10.0)]).rule is None


def test_deterministic():
    lines = _lines(REFERENCE["scenarios"][11]["lines"])
    outcomes = {
        (o.rule.id, o.deciding_index, o.split_advice)
        for o in (engine.evaluate(ACME_RULES, lines) for _ in range(20))
    }
    assert len(outcomes) == 1


@pytest.mark.parametrize(
    "description, total, small",
    [
        ("Tool subscription, monthly", 166.66, True),   # 1,999.92 / year
        ("Tool subscription, monthly", 166.67, False),  # 2,000.04 / year
        ("Tool subscription per month", 100.0, True),
        ("Tool subscription, annual", 1999.99, True),
        ("Tool subscription, annual", 2000.0, False),
    ],
)
def test_small_means_annualised_below_2000(description, total, small):
    outcome = engine.evaluate(ACME_RULES, [engine.Line(description, 1, total, total)])
    assert (outcome.rule is not None) is small


def test_amount_limit_applies_to_all_covered_lines_together():
    lines = [
        engine.Line("Chat subscription, annual", 1, 1200.0, 1200.0),
        engine.Line("Design tool subscription, annual", 1, 900.0, 900.0),
    ]
    assert engine.evaluate(ACME_RULES, lines).rule is None  # 2,100 a year in total


def test_more_specific_rule_wins():
    general = engine.Rule(uuid.uuid4(), "Cables", "", ("cable*",), (), 99)
    specific = engine.Rule(uuid.uuid4(), "Cable ties", "", ("cable tie*",), (), 11)
    outcome = engine.evaluate([general, specific], [engine.Line("Cable ties black", 1, 5.0, 5.0)])
    assert outcome.rule.name == "Cable ties"


def test_empty_rules_or_lines():
    assert engine.evaluate([], [engine.Line("Toner", 1, 1.0, 1.0)]).rule is None
    assert engine.evaluate(ACME_RULES, []).rule is None
    assert engine.evaluate(ACME_RULES, [engine.Line("   ")]).deciding_index is None


def test_overlapping_terms_warn():
    a = engine.Rule(uuid.uuid4(), "Toner A", "", ("toner*", "drum"), (), 29)
    b = engine.Rule(uuid.uuid4(), "Toner B", "", ("TONER*",), (), 204)
    assert engine.overlapping_terms(a, [b]) and not engine.overlapping_terms(a, [a])


@pytest.mark.parametrize(
    "term, text, expected",
    [
        ("cable tie*", "Releasable CABLE  TIES, 300 mm", True),
        ("cable tie*", "cable", False),
        ("tn-*", "Brother TN-2420", True),
        ("tn-*", "button-down shirt", False),
        ("ink", "Ink cartridge", True),
        ("ink", "Pink sticky notes", False),
        ("per-seat licen*", "CRM per-seat licenses", True),
    ],
)
def test_term_matching(term, text, expected):
    assert bool(engine.matched_terms([term], text)) is expected
