"""Catalog suggestions: retrieve with embeddings, confirm with a small model (spec 002).

Embeddings rank candidates well but cannot tell "the same kind of item" from a
look-alike (an acrylic logo scores higher against "Desk organizer acrylic" than
a MacBook does against "Business laptop"), so the top candidates are confirmed
by an LLM relevance check. Without the AI service the lookup falls back to
exact-token matching; it never raises for matching problems (FR-027).
"""
import logging
import math
import threading
import time
import uuid
from array import array
from collections import OrderedDict
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import openai
from openai import OpenAI
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Article, Supplier
from app.schemas.catalog import (
    ContractedSupplier,
    LineSuggestions,
    RelevanceVerdict,
    SuggestionLineIn,
    SuggestionsResponse,
)
from app.services import catalog_matching as rules
from app.services.catalog_matching import CatalogArticle, SupplierRef

logger = logging.getLogger(__name__)

# Unique descriptions retrieved per line before the relevance check.
CANDIDATES_PER_LINE = 6
_EMBED_BATCH = 1000

Embedder = Callable[[Sequence[str]], list[list[float]]]
# (line description, line unit, [(candidate description, candidate unit)]) -> keep flags
Verifier = Callable[[str, str, Sequence[tuple[str, str]]], list[bool]]

VERIFIER_PROMPT = (
    "You decide whether catalog articles are the SAME KIND of item as a requested order line, "
    "so the article could be bought instead. Same product type and purpose counts even if "
    "brand, size or specs differ (e.g. a specific laptop model vs a generic business laptop; a "
    "moss panel vs a moss wall). Different product types that only share a material, word or "
    "industry do NOT count (an acrylic logo is not a desk organizer; a grinding machine is not "
    "a machining service; installing a machine is not parcel delivery; a cyan toner is not a "
    "yellow toner). When unsure, answer false."
)


# ---------------------------------------------------------------------------
# Vectors
# ---------------------------------------------------------------------------


def model_tag() -> str:
    return f"{settings.embedding_model}@{settings.embedding_dimensions}"


def pack(vector: Sequence[float]) -> bytes:
    return array("f", vector).tobytes()


def unpack(blob: bytes) -> array:
    vector = array("f")
    vector.frombytes(blob)
    return vector


def _normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class _LRU:
    """Small thread-safe LRU cache (verdicts and line embeddings)."""

    def __init__(self, size: int):
        self.size = size
        self._data: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def put(self, key, value) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.size:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_line_vectors = _LRU(2000)
_verdicts = _LRU(5000)


# ---------------------------------------------------------------------------
# OpenAI-backed providers
# ---------------------------------------------------------------------------


def _client() -> OpenAI:
    return OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.suggestion_timeout_seconds,
        max_retries=1,
    )


def openai_embedder(texts: Sequence[str]) -> list[list[float]]:
    client = _client()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), _EMBED_BATCH):
        response = client.embeddings.create(
            model=settings.embedding_model,
            input=list(texts[start : start + _EMBED_BATCH]),
            dimensions=settings.embedding_dimensions,
        )
        vectors += [_normalize(item.embedding) for item in response.data]
    return vectors


def openai_verifier(
    line_description: str, line_unit: str, candidates: Sequence[tuple[str, str]]
) -> list[bool]:
    listing = "\n".join(
        f"{i}. {description} (unit: {unit})" for i, (description, unit) in enumerate(candidates)
    )
    completion = _client().chat.completions.parse(
        model=settings.suggestion_model,
        messages=[
            {"role": "system", "content": VERIFIER_PROMPT},
            {
                "role": "user",
                "content": f"Order line: {line_description} (unit: {line_unit or 'n/a'})\n"
                f"Candidates:\n{listing}\n"
                "Return same_kind with one boolean per candidate, in order.",
            },
        ],
        response_format=RelevanceVerdict,
        temperature=0,
        seed=7,
        max_completion_tokens=200,
    )
    verdict = completion.choices[0].message.parsed
    flags = list(verdict.same_kind) if verdict else []
    # A short or long answer must not shift verdicts onto the wrong candidate.
    return flags[: len(candidates)] + [False] * (len(candidates) - len(flags))


def default_providers() -> tuple[Embedder | None, Verifier | None]:
    """The AI providers, or (None, None) when no key is configured (lexical only)."""
    if not settings.openai_api_key:
        return None, None
    return openai_embedder, openai_verifier


# ---------------------------------------------------------------------------
# Catalog embeddings and the per-organization index
# ---------------------------------------------------------------------------


def ensure_embeddings(db: Session, organization_id: uuid.UUID, embedder: Embedder) -> int:
    """Embed the organization's articles that have no vector for the current model.

    Identical descriptions are embedded once. Returns the number of articles updated.
    """
    tag = model_tag()
    missing = list(
        db.scalars(
            select(Article).where(
                Article.organization_id == organization_id,
                (Article.embedding_model.is_(None)) | (Article.embedding_model != tag),
            )
        )
    )
    if not missing:
        return 0
    descriptions = sorted({a.description for a in missing})
    vectors = dict(zip(descriptions, embedder(descriptions)))
    for article in missing:
        article.embedding = pack(vectors[article.description])
        article.embedding_model = tag
    db.commit()
    return len(missing)


@dataclass
class _Entry:
    description: str
    vector: array
    articles: list[CatalogArticle]


@dataclass
class _OrgIndex:
    signature: tuple
    entries: list[_Entry]
    all_articles: list[CatalogArticle]


_indexes: dict[uuid.UUID, _OrgIndex] = {}
_index_lock = threading.Lock()


def _signature(db: Session, organization_id: uuid.UUID) -> tuple:
    total, embedded = db.execute(
        select(
            func.count(Article.id),
            func.count(Article.embedding_model).filter(Article.embedding_model == model_tag()),
        ).where(Article.organization_id == organization_id)
    ).one()
    return (total, embedded, model_tag())


def _load_index(db: Session, organization_id: uuid.UUID) -> _OrgIndex:
    signature = _signature(db, organization_id)
    with _index_lock:
        cached = _indexes.get(organization_id)
        if cached is not None and cached.signature == signature:
            return cached

    rows = db.execute(
        select(Article, Supplier.name, Supplier.vat_id)
        .join(Supplier, Supplier.id == Article.supplier_id)
        .where(Article.organization_id == organization_id)
        .order_by(Article.article_number)
    ).all()
    by_description: dict[str, _Entry] = {}
    all_articles: list[CatalogArticle] = []
    for article, supplier_name, supplier_vat_id in rows:
        item = CatalogArticle(
            id=article.id,
            article_number=article.article_number,
            description=article.description,
            supplier_id=article.supplier_id,
            supplier_name=supplier_name,
            unit_price=float(article.unit_price),
            unit=article.unit,
            currency=article.currency,
            min_quantity=float(article.quantity),
            supplier_vat_id=supplier_vat_id,
        )
        all_articles.append(item)
        if article.embedding is None or article.embedding_model != model_tag():
            continue
        entry = by_description.get(article.description)
        if entry is None:
            entry = by_description[article.description] = _Entry(
                article.description, unpack(article.embedding), []
            )
        entry.articles.append(item)

    index = _OrgIndex(signature, list(by_description.values()), all_articles)
    with _index_lock:
        _indexes[organization_id] = index
    return index


def reset_caches() -> None:
    """Forget cached indexes, line vectors and verdicts (tests, catalog reloads)."""
    with _index_lock:
        _indexes.clear()
    _line_vectors.clear()
    _verdicts.clear()


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _embed_lines(
    organization_id: uuid.UUID, texts: Sequence[str], embedder: Embedder
) -> list[Sequence[float]]:
    keys = [(organization_id, rules.normalize_text(t)) for t in texts]
    vectors: list = [_line_vectors.get(k) for k in keys]
    missing = sorted({t for t, v in zip(texts, vectors) if v is None})
    if missing:
        fresh = dict(zip(missing, embedder(missing)))
        for i, text in enumerate(texts):
            if vectors[i] is None:
                vectors[i] = fresh[text]
                _line_vectors.put(keys[i], fresh[text])
    return vectors


def _verify(
    organization_id: uuid.UUID,
    line: SuggestionLineIn,
    candidates: list[_Entry],
    verifier: Verifier,
) -> list[bool]:
    line_key = rules.normalize_text(line.description)
    keys = [(organization_id, line_key, c.description) for c in candidates]
    flags = [_verdicts.get(k) for k in keys]
    todo = [i for i, f in enumerate(flags) if f is None]
    if todo:
        fresh = verifier(
            line.description,
            line.unit,
            [(candidates[i].description, candidates[i].articles[0].unit) for i in todo],
        )
        for i, flag in zip(todo, fresh):
            flags[i] = bool(flag)
            _verdicts.put(keys[i], bool(flag))
    return [bool(f) for f in flags]


def _semantic_matches(
    organization_id: uuid.UUID,
    index: _OrgIndex,
    lines: Sequence[SuggestionLineIn],
    embedder: Embedder,
    verifier: Verifier,
) -> list[list[tuple[CatalogArticle, float]]]:
    active = [i for i, line in enumerate(lines) if line.description.strip()]
    results: list[list[tuple[CatalogArticle, float]]] = [[] for _ in lines]
    if not active or not index.entries:
        return results
    vectors = _embed_lines(organization_id, [lines[i].description for i in active], embedder)

    shortlists: dict[int, list[tuple[_Entry, float]]] = {}
    for i, vector in zip(active, vectors):
        scored = sorted(
            ((entry, _dot(vector, entry.vector)) for entry in index.entries),
            key=lambda pair: pair[1],
            reverse=True,
        )
        shortlists[i] = scored[:CANDIDATES_PER_LINE]

    def check(i: int) -> list[bool]:
        return _verify(organization_id, lines[i], [e for e, _ in shortlists[i]], verifier)

    # Lines are independent: confirm them concurrently so a quote's lines cost
    # about one round-trip.
    with ThreadPoolExecutor(max_workers=min(8, len(active))) as pool:
        verdicts = dict(zip(active, pool.map(check, active)))

    for i in active:
        for (entry, score), keep in zip(shortlists[i], verdicts[i]):
            if keep:
                results[i] += [(article, score) for article in entry.articles]
    return results


def _lexical_matches(
    index: _OrgIndex, lines: Sequence[SuggestionLineIn]
) -> list[list[tuple[CatalogArticle, float]]]:
    return [
        [
            (article, 1.0)
            for article in index.all_articles
            if line.description.strip() and rules.lexical_match(line.description, article.description)
        ]
        for line in lines
    ]


def suggest(
    db: Session,
    organization_id: uuid.UUID,
    lines: Sequence[SuggestionLineIn],
    *,
    vendor_name: str | None = None,
    vendor_vat_id: str | None = None,
    limit: int = 3,
    providers: tuple[Embedder | None, Verifier | None] | None = None,
) -> SuggestionsResponse:
    """Suggest catalog articles for each line from the organization's own catalog."""
    started = time.monotonic()
    embedder, verifier = providers if providers is not None else default_providers()

    suppliers = [
        SupplierRef(s.id, s.name, s.vat_id)
        for s in db.scalars(select(Supplier).where(Supplier.organization_id == organization_id))
    ]
    vendor = rules.match_supplier(vendor_name, vendor_vat_id, suppliers)
    contracted = ContractedSupplier(id=vendor.id, name=vendor.name) if vendor else None

    source = "lexical"
    index = _load_index(db, organization_id)
    if not index.all_articles:
        matches: list[list[tuple[CatalogArticle, float]]] = [[] for _ in lines]
    else:
        matches = None
        if embedder is not None and verifier is not None:
            try:
                if ensure_embeddings(db, organization_id, embedder):
                    index = _load_index(db, organization_id)
                matches = _semantic_matches(organization_id, index, lines, embedder, verifier)
                source = "semantic"
            except (openai.OpenAIError, TimeoutError, ValueError):
                db.rollback()
                logger.warning("Catalog matching service unavailable; using exact matches")
        if matches is None:
            matches = _lexical_matches(index, lines)

    result_lines = []
    for line, found in zip(lines, matches):
        suggestions = [
            rules.build_suggestion(
                article, line, relevance=score, vendor_supplier_id=vendor.id if vendor else None
            )
            for article, score in found
        ]
        ranked = rules.rank(suggestions, limit)
        # The vendor's own agreement may rank outside the top N; check all matches.
        result_lines.append(
            LineSuggestions(
                key=line.key,
                suggestions=ranked,
                agreement_check=rules.agreement_check(suggestions),
            )
        )

    logger.info(
        "catalog suggestions org=%s lines=%d source=%s duration_ms=%d",
        organization_id,
        len(lines),
        source,
        round((time.monotonic() - started) * 1000),
    )
    return SuggestionsResponse(source=source, contracted_supplier=contracted, lines=result_lines)
