"""Deterministic evaluation of organization booking rules (spec 003).

A rule covers an order line when one of its include terms appears in the
line's description and none of its exclude terms does. Terms are
case-insensitive phrases on word boundaries; a trailing ``*`` also matches word
continuations ("cable tie*" -> "cable ties", "cable tie mounts"; "tn-*" ->
"TN-2420"). An optional amount limit applies to the annualised total of the
lines a rule covers. Pure code: the same request always yields the same outcome.
"""
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache

_MONTHLY = re.compile(
    r"\b(monthly|per\s+month|a\s+month|each\s+month|/\s*mo(nth)?)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Rule:
    id: uuid.UUID
    name: str
    description: str
    include_terms: tuple[str, ...]
    exclude_terms: tuple[str, ...]
    target_group_id: int
    max_annual_amount: float | None = None


@dataclass(frozen=True)
class Line:
    description: str
    quantity: float = 1
    unit_price: float | None = None
    total_price: float | None = None


@dataclass
class Outcome:
    """Which rule (if any) decides the request's commodity group, and why."""

    rule: Rule | None = None
    deciding_index: int | None = None
    # Line index -> rule covering it (after amount conditions).
    covered: dict[int, Rule] = field(default_factory=dict)
    split_advice: bool = False

    @property
    def mandated_group_id(self) -> int | None:
        return self.rule.target_group_id if self.rule else None


@lru_cache(maxsize=512)
def compile_term(term: str) -> re.Pattern:
    text = " ".join(term.casefold().split())
    wildcard = text.endswith("*")
    body = re.escape(text.rstrip("*").strip()).replace(r"\ ", r"\s+")
    return re.compile(
        rf"(?<![a-z0-9]){body}" + (r"[\w-]*" if wildcard else r"(?![a-z0-9])"),
        re.IGNORECASE,
    )


def matched_terms(terms: Iterable[str], text: str) -> list[str]:
    return [term for term in terms if compile_term(term).search(text or "")]


def line_value(line: Line) -> float:
    if line.total_price is not None:
        return line.total_price
    if line.unit_price is not None:
        return line.unit_price * (line.quantity or 0)
    return 0.0


def annualised(line: Line) -> float:
    """Yearly cost of a line: monthly prices × 12; otherwise the total counts as yearly."""
    value = line_value(line)
    return value * 12 if _MONTHLY.search(line.description or "") else value


def line_rule(rules: Sequence[Rule], line: Line) -> Rule | None:
    """The most specific rule whose terms cover the line (amount not yet checked)."""
    matches: list[tuple[int, str, Rule]] = []
    for rule in rules:
        if matched_terms(rule.exclude_terms, line.description):
            continue
        hits = matched_terms(rule.include_terms, line.description)
        if hits:
            matches.append((max(len(term.rstrip("*")) for term in hits), rule.name, rule))
    if not matches:
        return None
    # Longer matched term = more specific; ties broken by name for determinism.
    matches.sort(key=lambda m: (-m[0], m[1]))
    return matches[0][2]


def evaluate(rules: Sequence[Rule], lines: Sequence[Line]) -> Outcome:
    """Apply the rules to a request's lines (spec 003, FR-003 – FR-011)."""
    if not rules or not lines:
        return Outcome()
    covered = {
        index: rule
        for index, line in enumerate(lines)
        if line.description.strip() and (rule := line_rule(rules, line)) is not None
    }
    # Amount conditions apply to the total of all lines a rule covers (FR-009).
    for rule in {r.id: r for r in covered.values()}.values():
        if rule.max_annual_amount is None:
            continue
        indexes = [i for i, r in covered.items() if r.id == rule.id]
        total = sum(annualised(lines[i]) for i in indexes)
        if round(total, 2) >= rule.max_annual_amount:
            for i in indexes:
                del covered[i]

    candidates = [i for i, line in enumerate(lines) if line.description.strip()]
    if not candidates:
        return Outcome()
    # The highest-value line decides; earlier lines win ties (FR-011).
    deciding = max(candidates, key=lambda i: (line_value(lines[i]), -i))
    return Outcome(
        rule=covered.get(deciding),
        deciding_index=deciding,
        covered=covered,
        split_advice=len({r.id for r in covered.values()}) > 1,
    )


def explanation(rule: Rule, organization_name: str, group_label: str) -> str:
    return f"{organization_name} booking rule: {rule.name} is booked under {group_label}."


def overlapping_terms(rule: Rule, others: Iterable[Rule]) -> list[str]:
    """Warnings for include terms that another active rule also uses."""
    warnings = []
    mine = {t.casefold() for t in rule.include_terms}
    for other in others:
        if other.id == rule.id:
            continue
        shared = sorted(mine & {t.casefold() for t in other.include_terms})
        if shared:
            warnings.append(
                f"Shares terms with rule '{other.name}': {', '.join(shared)}. "
                "The more specific term wins when both match."
            )
    return warnings
