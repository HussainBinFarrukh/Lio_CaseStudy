# Implementation Plan: Organization-Specific Commodity Booking Rules

**Branch**: `003-org-booking-rules` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-org-booking-rules/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Acme's three accounting quirks become **deterministic, org-scoped booking rules** that take
precedence over classification, are enforced on the server for requesters, can be overridden by
buyers/admins with a logged reason, and are managed by admins. General classification moves out
of the extraction call into its own stage (embedding shortlist over base groups + anchors, small
model pick) — which also repairs the empty commodity group observed after Task 1. See
[research.md](./research.md) (two live experiments).

## Technical Context

**Language/Version**: Python 3.11+ (image 3.12); TypeScript 5 strict

**Primary Dependencies**: FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, OpenAI SDK (embeddings +
`chat.completions.parse`); Next.js 15, React 19, TanStack Query 5. **No new dependencies.**

**Storage**: PostgreSQL 16; migration `0009_booking_rules` (2 tables, request + group columns)

**Testing**: pytest + TestClient (SQLite) with stub embedder/LLM; `tsc` + `next build`;
`scripts/eval_classification.py` (live)

**Target Platform / Project Type**: Docker Compose web app (FastAPI + Next.js)

**Performance Goals**: rule evaluation < 10 ms (pure); classification ≈ 0.5 s median (cached per
line set); no extra wait when no rule applies (SC-007)

**Constraints**: rules deterministic and org-scoped; AI failure never blocks saving; requesters
cannot bypass rules via the API

**Scale/Scope**: 2,000 groups (380 base), Acme 3 seeded rules; ~8 backend files, ~5 frontend files

## Constitution Check

| # | Principle | Pre | Post-design evidence |
| --- | --- | --- | --- |
| I | Tenant isolation | ✅ | Rules/events org-scoped (`organization_id` FK + filters, other org's rule → 404); Walmart test shows no rule effect; no org-specific groups. |
| II | Server-enforced roles | ✅ | Rule CRUD/check/rebook via `require_org_admin`; requester vs buyer/admin enforcement in the request router; tests for each path. |
| III | Layered backend | ✅ | `services/booking_rules.py` (pure), `services/classification.py` (I/O), `routers/booking_rules.py`, `routers/classification.py`. |
| IV | Typed, stable API | ✅ | Additive optional request fields; new typed endpoints; TS client updated; extraction response shape unchanged. |
| V | Tenant config, enforced after AI | ✅ | Rules are org data in an org-scoped table, applied deterministically after (and independent of) the model, on create **and** update. |
| VI | Trustworthy AI | ✅ | Model only proposes the general group from a validated shortlist; rules never depend on it; uncertain matches are hints. |
| VII | Auditable | ✅ | Overrides and re-bookings in the request activity log; rule changes in `booking_rule_events`. |
| VIII | Data integrity | ✅ | Additive migration with downgrade; CHECK constraint for `commodity_source` mirrored by a `Literal`; seed idempotent by (org, name). |
| IX | Tests | ✅ | Offline tests per story; R1–R14 asserted. |
| X | Frontend conventions | ✅ | `@/lib/api`, TanStack Query, base components, tokens. |
| XI | Simplicity | ✅ | Term rules instead of a rule engine; reuse Task 2 embedding/caching. |

**Result**: PASS before and after design.

## Project Structure

```text
lio-procurement-app/backend/
├── alembic/versions/0009_booking_rules.py        # NEW
├── app/models/booking_rule.py                    # NEW BookingRule, BookingRuleEvent
├── app/models/commodity_group.py, procurement_request.py   # new columns
├── app/schemas/booking_rules.py                  # NEW rule + classification schemas
├── app/schemas/requests.py                       # commoditySource, bookingRuleId, overrideReason; outputs
├── app/services/booking_rules.py                 # NEW pure: terms, annualisation, outcome, overlap
├── app/services/classification.py                # NEW shortlist + pick + hints + classify()
├── app/services/extraction.py                    # drop group list from prompt; fill group via classify()
├── app/routers/classification.py, booking_rules.py   # NEW
├── app/routers/requests.py                       # enforcement + provenance + override log
├── app/embed_catalog.py                          # also embeds base commodity groups
├── app/seed.py                                   # Acme rules if absent
├── scripts/eval_classification.py                # NEW live R1–R14 × orgs
└── tests/ test_booking_rules.py, test_classification.py, fixtures/booking_reference.json, test_smoke.py
lio-procurement-app/frontend/src/
├── lib/api/index.ts, types/database.ts
├── app/dashboard/new-request/page.tsx            # classification query, rule note, lock, hints, override reason
├── app/dashboard/requests/[id]/page.tsx          # provenance; edit lock / override reason
└── app/dashboard/organization/page.tsx           # "Booking rules" tab: CRUD, history, check & re-book
```

## Delivery Order

US1 (rules + classification + form) → US2 (enforcement, overrides) → US3 (isolation tests) →
US4 (terms/hints) → US5 (mixed lines) → US6 (admin CRUD + audit) → US7 (check & re-book).

## Complexity Tracking

No violations.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
