"""Live evaluation of catalog suggestions on the spec 002 reference scenarios (FR-025).

Seeds an in-memory database with the demo catalog, then runs every reference line
(Appendix A, ``tests/fixtures/catalog_reference.json``) through the real pipeline
(embeddings + relevance check) and checks: expected articles in the top 3, the
first-ranked article, no "must not" article, saving / extra-cost figures to the
cent, the contracted-supplier check, and per-line latency (SC-006). Caches are
cleared before each run, so latencies are for uncached lookups. Needs
``OPENAI_API_KEY``; not part of pytest.

    cd backend
    python scripts/eval_suggestions.py --runs 3
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.db.base import Base
from app.models import Organization
from app.schemas.catalog import SuggestionLineIn
from app.seed import seed
from app.services import catalog_search


def check(case: dict, line) -> list[str]:
    """Return the problems found for one reference line (empty = pass)."""
    problems = []
    numbers = [s.article_number for s in line.suggestions]
    for expected in case["expected"]:
        if expected not in numbers:
            problems.append(f"missing {expected}")
    if case["first"] and (not numbers or numbers[0] != case["first"]):
        problems.append(f"first is {numbers[0] if numbers else None}, want {case['first']}")
    if not case["expected"] and numbers:
        problems.append(f"expected no suggestion, got {numbers}")
    for s in line.suggestions:
        if any(bad in s.description.lower() for bad in case["must_not"]):
            problems.append(f"must-not article {s.article_number} {s.description!r}")
    by_number = {s.article_number: s for s in line.suggestions}
    for number, effect in case["effects"].items():
        got = by_number.get(number)
        if got is None:
            continue
        if effect is None and got.line_effect is not None:
            problems.append(f"{number}: expected no comparison, got {got.line_effect}")
        elif effect is not None and (got.line_effect is None or abs(got.line_effect - effect) > 0.01):
            problems.append(f"{number}: effect {got.line_effect}, want {effect}")
    if "agreement_difference" in case:
        check_ = line.agreement_check
        if check_ is None or abs(check_.difference - case["agreement_difference"]) > 0.01:
            problems.append(f"agreement check {check_}, want +{case['agreement_difference']}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--fixture", type=Path, default=BACKEND_DIR / "tests/fixtures/catalog_reference.json"
    )
    parser.add_argument("--verbose", action="store_true", help="print the suggestions per line")
    args = parser.parse_args()
    if not settings.openai_api_key:
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 2

    cases = json.loads(args.fixture.read_text(encoding="utf-8"))["lines"]
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        seed(db)
        acme = db.scalar(select(Organization.id).where(Organization.slug == "acme"))
        started = time.monotonic()
        embedded = catalog_search.ensure_embeddings(db, acme, catalog_search.openai_embedder)
        print(f"Embedded {embedded} articles in {time.monotonic() - started:.1f}s")

    failures = 0
    latencies: list[float] = []
    for run in range(1, args.runs + 1):
        catalog_search.reset_caches()
        for case in cases:
            line_in = SuggestionLineIn(
                key=case["id"], description=case["description"], unit=case["unit"],
                quantity=case["quantity"], unit_price=case.get("unit_price"),
                discount_percent=case.get("discount_percent", 0),
                total_price=case.get("total_price"),
            )
            with session_factory() as db:
                started = time.monotonic()
                result = catalog_search.suggest(
                    db, acme, [line_in], vendor_name=case.get("vendor_name")
                )
                latencies.append(time.monotonic() - started)
            line = result.lines[0]
            problems = check(case, line)
            if result.source != "semantic":
                problems.append(f"source {result.source}")
            failures += bool(problems)
            print(f"{'ok  ' if not problems else 'FAIL'}  run {run} {case['id']:<4} "
                  f"{latencies[-1] * 1000:5.0f} ms  " + "; ".join(problems))
            if args.verbose:
                for s in line.suggestions:
                    print(f"        {s.article_number} {s.unit_price:>9.2f}/{s.unit:<6} "
                          f"effect {s.line_effect}  {s.description[:50]}")

    total = len(cases) * args.runs
    ordered = sorted(latencies)
    p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
    print(f"\nLines: {total}  failed: {failures}")
    print(f"Latency (uncached): median {statistics.median(latencies) * 1000:.0f} ms, "
          f"p95 {p95 * 1000:.0f} ms, max {max(latencies) * 1000:.0f} ms")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
