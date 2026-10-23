"""Live evaluation of commodity classification and booking rules (spec 003, FR-024).

Seeds an in-memory database (taxonomy, organizations, Acme's booking rules) and
classifies every Appendix A scenario (``tests/fixtures/booking_reference.json``)
for Acme and Walmart through the real pipeline. Checks: Acme's rule scenarios get
the mandated group via the rule; no other scenario is decided by a rule; Walmart
never gets a rule. Prints the system group for the rest. Needs ``OPENAI_API_KEY``.

    cd backend
    python scripts/eval_classification.py --runs 3
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
from app.schemas.booking_rules import ClassificationLineIn
from app.seed import seed
from app.services import classification


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--fixture", type=Path, default=BACKEND_DIR / "tests/fixtures/booking_reference.json"
    )
    args = parser.parse_args()
    if not settings.openai_api_key:
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 2

    scenarios = json.loads(args.fixture.read_text(encoding="utf-8"))["scenarios"]
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        seed(db)
        orgs = {
            slug: db.scalar(select(Organization.id).where(Organization.slug == slug))
            for slug in ("acme", "walmart")
        }

    failures = 0
    latencies = []
    for run in range(1, args.runs + 1):
        classification.reset_caches()
        for scenario in scenarios:
            lines = [ClassificationLineIn(**line) for line in scenario["lines"]]
            row = []
            for slug, org_id in orgs.items():
                with session_factory() as db:
                    started = time.monotonic()
                    result = classification.classify(db, org_id, lines)
                    latencies.append(time.monotonic() - started)
                problems = []
                rule = result.rule.name if result.rule else None
                if slug == "acme":
                    if rule != scenario["acme_rule"]:
                        problems.append(f"rule {rule!r}, want {scenario['acme_rule']!r}")
                    if scenario["acme_group"] and result.commodity_group_id != scenario["acme_group"]:
                        problems.append(f"group {result.commodity_group_id}, want {scenario['acme_group']}")
                    if scenario.get("split_advice") and not result.split_advice:
                        problems.append("missing split advice")
                elif rule is not None:
                    problems.append(f"rule {rule!r} applied to {slug}")
                failures += bool(problems)
                hints = ",".join(h.rule_name for h in result.hints)
                row.append(
                    f"{slug}: {result.commodity_group_id} {result.commodity_group_name or '-'}"
                    f" [{result.source}]" + (f" hint={hints}" if hints else "")
                    + (f"  FAIL {'; '.join(problems)}" if problems else "")
                )
            print(f"run {run} {scenario['id']:<4} " + " | ".join(row))

    print(f"\nScenarios × orgs × runs: {len(scenarios) * len(orgs) * args.runs}  failed: {failures}")
    print(f"Latency (uncached): median {statistics.median(latencies) * 1000:.0f} ms, "
          f"max {max(latencies) * 1000:.0f} ms")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
