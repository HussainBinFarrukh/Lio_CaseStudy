"""Live evaluation of quote extraction against the reference quotes (spec 001, FR-029).

Runs the real pipeline (PDF text -> OpenAI -> rules) N times per quote and reports
per-field accuracy and the hard-failure rate against
``tests/fixtures/reference_quotes.json``. Needs ``OPENAI_API_KEY``; not part of
pytest because it calls the external service.

    cd backend
    python scripts/eval_extraction.py --quotes ../../quotes --runs 3

Exits non-zero if any field is below ``--min-accuracy`` or any run hard-fails.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.db.base import Base
from app.seed import seed_commodity_groups
from app.services.extraction import extract_vendor_data
from app.services.pdf import extract_text

FIELDS = (
    "vendor", "vat_id", "lines", "net_total", "grand_total",
    "quote_number", "quote_date", "valid_until",
)
TOLERANCE = 0.02


def _close(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) <= TOLERANCE


def score(data, expected: dict) -> dict[str, bool]:
    line_totals = [line.total_price for line in data.order_lines]
    return {
        "vendor": data.vendor_name in expected["vendor"],
        "vat_id": data.vat_id == expected["vat_id"],
        "lines": len(line_totals) == len(expected["line_totals"])
        and all(_close(a, b) for a, b in zip(line_totals, expected["line_totals"])),
        "net_total": _close(data.totals.net_total, expected["net_total"]),
        "grand_total": _close(data.total_cost, expected["grand_total"]),
        "quote_number": data.quote_number == expected["quote_number"],
        "quote_date": data.quote_date == expected["quote_date"],
        "valid_until": data.valid_until == expected["valid_until"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quotes", type=Path, default=BACKEND_DIR.parents[1] / "quotes")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--min-accuracy", type=float, default=1.0)
    parser.add_argument(
        "--fixture", type=Path, default=BACKEND_DIR / "tests/fixtures/reference_quotes.json"
    )
    args = parser.parse_args()

    if not settings.openai_api_key:
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 2

    reference = json.loads(args.fixture.read_text(encoding="utf-8"))
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        seed_commodity_groups(db)
        db.commit()

    hits: dict[str, int] = defaultdict(int)
    total_runs = hard_failures = 0
    for filename, expected in reference["quotes"].items():
        text = extract_text((args.quotes / filename).read_bytes())
        for run in range(1, args.runs + 1):
            total_runs += 1
            with session_factory() as db:
                response = extract_vendor_data(text, db, buyer_names=reference["buyer_names"])
            if not response.success:
                hard_failures += 1
                print(f"FAIL  {filename} run {run}: {response.error_code}")
                continue
            result = score(response.data, expected)
            for field, ok in result.items():
                hits[field] += ok
            wrong = [f for f, ok in result.items() if not ok]
            print(f"{'ok  ' if not wrong else 'DIFF'}  {filename} run {run}"
                  + (f": {', '.join(wrong)}" if wrong else ""))

    print(f"\nRuns: {total_runs}  hard failures: {hard_failures}")
    print(f"{'field':<14}accuracy")
    worst = 1.0
    for field in FIELDS:
        accuracy = hits[field] / total_runs if total_runs else 0.0
        worst = min(worst, accuracy)
        print(f"{field:<14}{accuracy:6.0%}")
    return 0 if hard_failures == 0 and worst >= args.min_accuracy else 1


if __name__ == "__main__":
    sys.exit(main())
