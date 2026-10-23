"""Commodity-group classification for a request's order lines (spec 003).

1. **Booking rules** (deterministic, org-specific) decide first.
2. Otherwise the **system** proposes a group: embeddings shortlist the base
   commodity groups (size/tier variants collapsed) plus general anchors, and a
   small model picks one. Choosing among 2,000 groups inside the extraction
   call returned no group at all; a separate, focused step does not.
3. Lines that look like a rule's items but don't match its terms get a
   **hint** the requester can accept — never applied silently.

AI problems never raise: rules still apply, the system proposal and hints are
simply absent.
"""
import logging
import threading
import time
import uuid
from collections.abc import Callable, Sequence

import openai
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BookingRule, CommodityGroup, Organization
from app.schemas.booking_rules import (
    AppliedRule,
    ClassificationLineIn,
    ClassificationOut,
    DecidingLine,
    GroupPick,
    RuleHint,
)
from app.services import booking_rules as engine
from app.services import catalog_search
from app.services.catalog_search import Embedder

logger = logging.getLogger(__name__)

# Always offered to the model besides the shortlist: the general buckets.
ANCHOR_GROUP_IDS = (15, 29, 30, 31)
SHORTLIST_SIZE = 12
# Similarity to a rule's text above which an unmatched line gets a hint.
HINT_THRESHOLD = 0.50
_VARIANT_SEPARATOR = " — "  # "Toner Cartridges — Bulk" is a variant of 204

# (line descriptions, [(group id, "category / name")]) -> chosen id or None
Picker = Callable[[Sequence[str], Sequence[tuple[int, str]]], int | None]

PICKER_PROMPT = (
    "You classify a procurement request into exactly one commodity group for accounting. "
    "Choose the group that best describes the PRIMARY items being bought (the main, "
    "highest-value item). Prefer the most specific group that names the item. Choose only "
    "from the candidate list; return null only if none plausibly fits."
)


def openai_picker(lines: Sequence[str], candidates: Sequence[tuple[int, str]]) -> int | None:
    listing = "\n".join(f"{gid} | {label}" for gid, label in candidates)
    completion = catalog_search._client().chat.completions.parse(
        model=settings.suggestion_model,
        messages=[
            {"role": "system", "content": PICKER_PROMPT},
            {
                "role": "user",
                "content": "Order lines:\n"
                + "\n".join(f"- {line}" for line in lines)
                + f"\n\nCandidates (id | category / name):\n{listing}",
            },
        ],
        response_format=GroupPick,
        temperature=0,
        seed=7,
        max_completion_tokens=50,
    )
    pick = completion.choices[0].message.parsed
    return pick.commodity_group_id if pick else None


def default_providers() -> tuple[Embedder | None, Picker | None]:
    if not settings.openai_api_key:
        return None, None
    return catalog_search.openai_embedder, openai_picker


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def to_engine_rule(rule: BookingRule) -> engine.Rule:
    return engine.Rule(
        id=rule.id,
        name=rule.name,
        description=rule.description or "",
        include_terms=tuple(rule.include_terms or ()),
        exclude_terms=tuple(rule.exclude_terms or ()),
        target_group_id=rule.target_commodity_group_id,
        max_annual_amount=(
            float(rule.max_annual_amount) if rule.max_annual_amount is not None else None
        ),
    )


def load_rules(db: Session, organization_id: uuid.UUID) -> list[engine.Rule]:
    rows = db.scalars(
        select(BookingRule)
        .where(BookingRule.organization_id == organization_id, BookingRule.active.is_(True))
        .order_by(BookingRule.name)
    )
    return [to_engine_rule(r) for r in rows]


def to_engine_lines(lines: Sequence[ClassificationLineIn]) -> list[engine.Line]:
    return [
        engine.Line(
            description=line.description,
            quantity=line.quantity,
            unit_price=line.unit_price,
            total_price=line.total_price,
        )
        for line in lines
    ]


# ---------------------------------------------------------------------------
# System classification (shortlist + pick)
# ---------------------------------------------------------------------------

_group_index: dict[str, list[tuple[int, str, object]]] = {}
_group_lock = threading.Lock()
_picks = catalog_search._LRU(2000)
_rule_vectors = catalog_search._LRU(500)


def ensure_group_embeddings(db: Session, embedder: Embedder) -> int:
    """Embed the base commodity groups that have no vector for the current model."""
    tag = catalog_search.model_tag()
    missing = [
        g
        for g in db.scalars(select(CommodityGroup))
        if _VARIANT_SEPARATOR not in g.name and g.embedding_model != tag
    ]
    if not missing:
        return 0
    vectors = embedder([f"{g.category} / {g.name}" for g in missing])
    for group, vector in zip(missing, vectors):
        group.embedding = catalog_search.pack(vector)
        group.embedding_model = tag
    db.commit()
    with _group_lock:
        _group_index.pop(tag, None)
    return len(missing)


def _groups(db: Session) -> list[tuple[int, str, object]]:
    tag = catalog_search.model_tag()
    with _group_lock:
        if tag in _group_index:
            return _group_index[tag]
    rows = [
        (g.id, f"{g.category} / {g.name}", catalog_search.unpack(g.embedding))
        for g in db.scalars(select(CommodityGroup).where(CommodityGroup.embedding_model == tag))
    ]
    with _group_lock:
        if rows:
            _group_index[tag] = rows
    return rows


def classify_system(
    db: Session, texts: Sequence[str], embedder: Embedder, picker: Picker
) -> int | None:
    """General classification of the given line descriptions (no rules)."""
    key = tuple(" ".join(t.casefold().split()) for t in texts)
    cached = _picks.get(key)
    if cached is not None:
        return cached or None
    ensure_group_embeddings(db, embedder)
    groups = _groups(db)
    if not groups:
        return None
    query = embedder([" ; ".join(texts)])[0]
    ranked = sorted(groups, key=lambda g: catalog_search._dot(query, g[2]), reverse=True)
    shortlist = [(gid, label) for gid, label, _ in ranked[:SHORTLIST_SIZE]]
    labels = {gid: label for gid, label, _ in groups}
    shortlist += [(a, labels[a]) for a in ANCHOR_GROUP_IDS if a in labels and a not in dict(shortlist)]
    chosen = picker(texts, shortlist)
    if chosen not in dict(shortlist):
        chosen = None
    _picks.put(key, chosen or 0)
    return chosen


def rule_hints(
    organization: Organization,
    rules: Sequence[engine.Rule],
    lines: Sequence[engine.Line],
    outcome: engine.Outcome,
    embedder: Embedder,
    group_names: dict[int, str],
) -> list[RuleHint]:
    """Hints for lines that resemble a rule's items without matching its terms (FR-010)."""
    candidates = [
        i for i, line in enumerate(lines) if line.description.strip() and i not in outcome.covered
    ]
    if not rules or not candidates:
        return []
    rule_vectors = []
    for rule in rules:
        text = f"{rule.name}: {rule.description}. Examples: " + ", ".join(
            t.rstrip("*") for t in rule.include_terms
        )
        vector = _rule_vectors.get((rule.id, text))
        if vector is None:
            vector = embedder([text])[0]
            _rule_vectors.put((rule.id, text), vector)
        rule_vectors.append(vector)
    line_vectors = catalog_search._embed_lines(
        organization.id, [lines[i].description for i in candidates], embedder
    )
    hints = []
    for i, vector in zip(candidates, line_vectors):
        best = None
        for rule, rule_vector in zip(rules, rule_vectors):
            if engine.matched_terms(rule.exclude_terms, lines[i].description):
                continue
            if (
                rule.max_annual_amount is not None
                and engine.annualised(lines[i]) >= rule.max_annual_amount
            ):
                continue
            score = catalog_search._dot(vector, rule_vector)
            if score >= HINT_THRESHOLD and (best is None or score > best[0]):
                best = (score, rule)
        if best:
            rule = best[1]
            target = group_names.get(rule.target_group_id, str(rule.target_group_id))
            hints.append(
                RuleHint(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    target_group_id=rule.target_group_id,
                    line_index=i,
                    message=(
                        f"This may fall under {organization.name}'s booking rule "
                        f"'{rule.name}' ({target})."
                    ),
                )
            )
    return hints


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def classify(
    db: Session,
    organization_id: uuid.UUID,
    lines: Sequence[ClassificationLineIn],
    *,
    providers: tuple[Embedder | None, Picker | None] | None = None,
) -> ClassificationOut:
    started = time.monotonic()
    embedder, picker = providers if providers is not None else default_providers()
    organization = db.get(Organization, organization_id)
    rules = load_rules(db, organization_id)
    engine_lines = to_engine_lines(lines)
    outcome = engine.evaluate(rules, engine_lines)
    result = ClassificationOut(split_advice=outcome.split_advice)

    if outcome.deciding_index is not None:
        result.deciding_line = DecidingLine(
            index=outcome.deciding_index,
            description=engine_lines[outcome.deciding_index].description,
        )

    group_names = {}
    if rules:
        ids = {r.target_group_id for r in rules}
        group_names = {
            g.id: f"{g.name} ({g.id})"
            for g in db.scalars(select(CommodityGroup).where(CommodityGroup.id.in_(ids)))
        }

    if outcome.rule is not None:
        rule = outcome.rule
        result.commodity_group_id = rule.target_group_id
        result.source = "rule"
        result.rule = AppliedRule(
            id=rule.id,
            name=rule.name,
            target_group_id=rule.target_group_id,
            explanation=engine.explanation(
                rule,
                organization.name if organization else "Organization",
                group_names.get(rule.target_group_id, str(rule.target_group_id)),
            ),
        )

    texts = [line.description for line in engine_lines if line.description.strip()]
    if embedder is not None and texts:
        try:
            if outcome.rule is None and picker is not None:
                result.commodity_group_id = classify_system(db, texts, embedder, picker)
                result.source = "system" if result.commodity_group_id else None
            if organization is not None:
                result.hints = rule_hints(
                    organization, rules, engine_lines, outcome, embedder, group_names
                )
        except (openai.OpenAIError, ValidationError, TimeoutError):
            db.rollback()
            logger.warning("Classification service unavailable; rules only")

    if result.commodity_group_id is not None:
        group = db.get(CommodityGroup, result.commodity_group_id)
        result.commodity_group_name = group.name if group else None
    logger.info(
        "classification org=%s lines=%d source=%s group=%s duration_ms=%d",
        organization_id,
        len(lines),
        result.source,
        result.commodity_group_id,
        round((time.monotonic() - started) * 1000),
    )
    return result


def reset_caches() -> None:
    with _group_lock:
        _group_index.clear()
    _picks.clear()
    _rule_vectors.clear()
