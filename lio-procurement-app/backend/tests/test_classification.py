"""Classification service with stub embedder / picker on a seeded database (no network)."""
import httpx
import openai
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Organization
from app.schemas.booking_rules import ClassificationLineIn
from app.seed import seed
from app.services import classification

_engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)


@event.listens_for(_engine, "connect")
def _fks(dbapi_connection, _record):
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


Base.metadata.create_all(_engine)
Session = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
with Session() as _s:
    seed(_s)
    ACME = _s.scalar(select(Organization.id).where(Organization.slug == "acme"))
    WALMART = _s.scalar(select(Organization.id).where(Organization.slug == "walmart"))

# Concept axes for the stub embedder: subscriptions/licenses, cables/ties, toner/printing, other.
_AXES = (("subscription", "license", "saas"), ("cable", "tie"), ("toner", "printer"))


class StubEmbedder:
    def __init__(self):
        self.calls = 0

    def __call__(self, texts):
        self.calls += 1
        vectors = []
        for text in texts:
            low = text.lower()
            v = [1.0 if any(w in low for w in words) else 0.0 for words in _AXES]
            if not any(v):
                v.append(1.0)
            else:
                v.append(0.0)
            n = sum(x * x for x in v) ** 0.5
            vectors.append([x / n for x in v])
        return vectors


class StubPicker:
    def __init__(self, choice):
        self.choice = choice
        self.candidates = None

    def __call__(self, lines, candidates):
        self.candidates = candidates
        return self.choice


def _lines(*items):
    return [
        ClassificationLineIn(description=d, quantity=1, unit_price=p, total_price=p) for d, p in items
    ]


def _classify(org, lines, providers=(None, None)):
    with Session() as db:
        return classification.classify(db, org, lines, providers=providers)


def test_rule_decides_without_any_ai():
    result = _classify(ACME, _lines(("Toner cartridge black, high-yield, HP 59A", 480.0)))
    assert (result.source, result.commodity_group_id, result.commodity_group_name) == (
        "rule", 29, "Hardware"
    )
    assert result.rule.name == "Printer toner"
    assert result.rule.explanation == (
        "Acme Corp booking rule: Printer toner is booked under Hardware (29)."
    )
    assert result.deciding_line.index == 0


def test_rules_are_organization_specific():
    picker = StubPicker(204)
    result = _classify(WALMART, _lines(("Toner cartridge black", 480.0)), (StubEmbedder(), picker))
    assert (result.source, result.commodity_group_id, result.rule) == ("system", 204, None)


def test_system_pick_comes_from_shortlist_with_anchors():
    picker = StubPicker(31)
    result = _classify(ACME, _lines(("ERP enterprise license, 500 seats", 85000.0)),
                       (StubEmbedder(), picker))
    assert (result.source, result.commodity_group_id) == ("system", 31)
    ids = [gid for gid, _label in picker.candidates]
    assert {15, 29, 30, 31} <= set(ids)
    # Size/tier variants are collapsed onto their base group.
    assert all("—" not in label for _gid, label in picker.candidates)


def test_pick_outside_shortlist_is_discarded():
    result = _classify(WALMART, _lines(("Something", 10.0)), (StubEmbedder(), StubPicker(99999)))
    assert (result.commodity_group_id, result.source) == (None, None)


def test_uncertain_match_is_a_hint_not_a_rule():
    result = _classify(
        ACME,
        _lines(("Video conferencing license host, annual", 500.0)),
        (StubEmbedder(), StubPicker(31)),
    )
    assert result.source == "system" and result.rule is None  # not applied silently
    assert [(h.rule_name, h.target_group_id, h.line_index) for h in result.hints] == [
        ("Small software subscriptions", 15, 0)
    ]
    assert "may fall under Acme Corp's booking rule" in result.hints[0].message


def test_hint_respects_amount_condition_and_excludes():
    result = _classify(
        ACME,
        _lines(("ERP license host, annual", 85000.0), ("Ink cartridge for printer", 40.0)),
        (StubEmbedder(), StubPicker(31)),
    )
    assert result.hints == []


def test_mixed_lines_highest_value_decides_with_split_advice():
    result = _classify(ACME, _lines(("Cable ties nylon", 170.0), ("Toner cartridge black", 480.0)))
    assert (result.commodity_group_id, result.deciding_line.index, result.split_advice) == (
        29, 1, True
    )


_REQUEST = httpx.Request("POST", "https://api.openai.example/v1/embeddings")


def test_ai_failure_keeps_rules_and_drops_the_rest():
    def broken(_texts):
        raise openai.APITimeoutError(request=_REQUEST)

    rule = _classify(ACME, _lines(("Cable ties", 170.0)), (broken, StubPicker(15)))
    assert (rule.source, rule.commodity_group_id) == ("rule", 11)
    other = _classify(ACME, _lines(("Copy paper", 98.0)), (broken, StubPicker(201)))
    assert (other.source, other.commodity_group_id, other.hints) == (None, None, [])


@pytest.mark.parametrize("org", [ACME, WALMART])
def test_empty_lines(org):
    assert _classify(org, _lines(("  ", 0.0))).commodity_group_id is None
