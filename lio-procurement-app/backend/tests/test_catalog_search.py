"""Suggestion pipeline on the seeded catalog with stub embedder and verifier (no network)."""
import math
import zlib

import httpx
import openai
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Article, Organization
from app.schemas.catalog import SuggestionLineIn
from app.seed import seed
from app.services import catalog_search
from app.services.catalog_matching import normalize_text

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

DIMS = 1024


class StubEmbedder:
    """Bag-of-words vectors: shared words -> high cosine. Counts calls."""

    def __init__(self):
        self.calls = 0
        self.texts = 0

    def __call__(self, texts):
        self.calls += 1
        self.texts += len(texts)
        vectors = []
        for text in texts:
            v = [0.0] * DIMS
            for token in normalize_text(text).split():
                v[zlib.crc32(token.encode()) % DIMS] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            vectors.append([x / n for x in v])
        return vectors


class StubVerifier:
    """Stands in for the LLM's 'same kind of item' decisions. Counts calls."""

    def __init__(self, accept: dict[str, set[str]]):
        self.accept = accept
        self.calls = 0

    def __call__(self, line, unit, candidates):
        self.calls += 1
        allowed = self.accept.get(line, set())
        return [description in allowed for description, _unit in candidates]


ACCEPT = {
    "verdeform CUSTOM module forest moss": {
        "Custom moss wall, preserved reindeer moss, made to measure"
    },
    "Toner cartridge cyan": {"Toner cartridge cyan"},
    # The verifier rejects every look-alike for the acrylic logo (R4).
    "Logo acrylic white with standoffs": set(),
}


def _line(description, unit="pieces", quantity=1, unit_price=None, total=None, key="0"):
    return SuggestionLineIn(
        key=key, description=description, unit=unit, quantity=quantity,
        unit_price=unit_price, total_price=total,
    )


@pytest.fixture
def providers():
    return StubEmbedder(), StubVerifier(ACCEPT)


def _suggest(lines, org=ACME, providers=None, **kwargs):
    with Session() as db:
        return catalog_search.suggest(db, org, lines, providers=providers, **kwargs)


def test_confirmed_match_with_saving(providers):
    result = _suggest(
        [_line("verdeform CUSTOM module forest moss", "sq ft", 13.78, 52.0, 716.56)],
        providers=providers,
    )
    assert result.source == "semantic"
    top = result.lines[0].suggestions[0]
    assert (top.article_number, top.supplier_name, top.line_effect) == (
        "HAR-00172", "Harborview Facility LLC", -102.11,
    )


def test_unconfirmed_candidates_are_never_suggested(providers):
    result = _suggest([_line("Logo acrylic white with standoffs")], providers=providers)
    assert result.lines[0].suggestions == []
    assert providers[1].calls == 1  # candidates were retrieved, then all rejected


def test_toner_offers_ranked_by_price_and_cached(providers):
    embedder, verifier = providers
    lines = [_line("Toner cartridge cyan", quantity=5, unit_price=150.0, total=750.0)]
    first = _suggest(lines, providers=providers)
    numbers = [s.article_number for s in first.lines[0].suggestions]
    assert numbers == ["MON-00922", "BEA-01877", "DEL-00890"]
    assert first.lines[0].suggestions[0].line_effect == -275.0
    assert first.lines[0].suggestions[0].below_min_quantity

    calls = (embedder.calls, verifier.calls)
    _suggest(lines, providers=providers)
    assert (embedder.calls, verifier.calls) == calls  # served from the caches


def test_catalog_embedded_once_per_description(providers):
    embedder, _ = providers
    with Session() as db:
        db.query(Article).update({Article.embedding: None, Article.embedding_model: None})
        db.commit()
        updated = catalog_search.ensure_embeddings(db, ACME, embedder)
        assert updated == 1920
        assert embedder.texts == 393  # unique descriptions only
        assert catalog_search.ensure_embeddings(db, ACME, embedder) == 0


def test_contracted_supplier_ranked_first_with_agreement_check(providers):
    result = _suggest(
        [_line("Toner cartridge cyan", quantity=10, unit_price=120.0, total=1200.0)],
        providers=providers,
        vendor_name="Montclair Supply Corp",
    )
    assert result.contracted_supplier.name == "Montclair Supply Corp."
    line = result.lines[0]
    assert line.suggestions[0].article_number == "MON-00922" and line.suggestions[0].from_vendor
    assert line.agreement_check.difference == 25.0


def test_empty_catalog_and_empty_lines(providers):
    embedder, verifier = providers
    result = _suggest([_line("Toner cartridge cyan")], org=WALMART, providers=providers)
    assert result.lines[0].suggestions == []
    assert (embedder.calls, verifier.calls) == (0, 0)
    result = _suggest([_line("   ")], providers=providers)
    assert result.lines[0].suggestions == []


_REQUEST = httpx.Request("POST", "https://api.openai.example/v1/embeddings")


@pytest.mark.parametrize(
    "error",
    [
        openai.APITimeoutError(request=_REQUEST),
        openai.RateLimitError("slow down", response=httpx.Response(429, request=_REQUEST), body=None),
    ],
)
def test_service_failure_falls_back_to_exact_matches(error):
    def broken(_texts):
        raise error

    result = _suggest(
        [_line("Toner cartridge cyan", key="a"), _line("Logo acrylic white with standoffs", key="b")],
        providers=(broken, StubVerifier(ACCEPT)),
    )
    assert result.source == "lexical"
    assert [s.article_number for s in result.lines[0].suggestions][:1] == ["MON-00922"]
    assert result.lines[1].suggestions == []


def test_no_key_uses_exact_matches():
    result = _suggest([_line("Toner cartridge cyan")])
    assert result.source == "lexical"
    assert result.lines[0].suggestions[0].article_number == "MON-00922"
