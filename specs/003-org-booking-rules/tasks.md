---

description: "Task list for Organization-Specific Commodity Booking Rules"
---

# Tasks: Organization-Specific Commodity Booking Rules

**Input**: `/specs/003-org-booking-rules/` (plan, spec, research, data-model, contracts, quickstart)

**Tests**: Required (constitution IX; FR-024/FR-025). Paths relative to `lio-procurement-app/`.

## Phase 1: Setup & Foundational

- [X] T001 Migration `backend/alembic/versions/0009_booking_rules.py`; models `backend/app/models/booking_rule.py`, columns on `commodity_group.py` and `procurement_request.py`
- [X] T002 Schemas `backend/app/schemas/booking_rules.py`; request schema fields in `backend/app/schemas/requests.py`
- [X] T003 Pure rules engine `backend/app/services/booking_rules.py` (terms with `*`, annualisation, outcome, overlap)
- [X] T004 Classification service `backend/app/services/classification.py` (group shortlist + pick, hints, `classify()`), group embedding in `backend/app/embed_catalog.py`
- [X] T005 Seed Acme rules (if absent) in `backend/app/seed.py`
- [X] T006 [P] Ground truth `backend/tests/fixtures/booking_reference.json`
- [X] T007 Frontend types/client `frontend/src/lib/api/index.ts`, `frontend/src/types/database.ts`

## Phase 2: US1 — Rules always applied (P1) 🎯

- [X] T008 [P] [US1] `backend/tests/test_booking_rules.py`: R1–R14 + variants deterministic
- [X] T009 [US1] `POST /classification` router; extraction uses `classify()` and drops the group list from its prompt
- [X] T010 [US1] New Request: classification query sets group, rule note

## Phase 3: US2 — Enforced & explained (P1)

- [X] T011 [US2] Enforcement/provenance/override log in `backend/app/routers/requests.py`; API tests
- [X] T012 [US2] Locked selector for requesters, override reason for buyers/admins (new-request + detail edit)

## Phase 4: US3 — Org-specific (P1)

- [X] T013 [US3] Tenant tests (Walmart unaffected; other org's rule → 404)

## Phase 5: US4 — Right items only (P2)

- [X] T014 [US4] Hints (embedding ≥ 0.50, excludes/conditions) + Apply; `backend/tests/test_classification.py` with stubs

## Phase 6: US5 — Mixed requests (P2)

- [X] T015 [US5] Highest-value line + split advice (engine + UI note); tests R11/R12

## Phase 7: US6 — Admin management (P2)

- [X] T016 [US6] `backend/app/routers/booking_rules.py` CRUD + events; tests (admin only, validation, audit)
- [X] T017 [US6] Organization page "Booking rules" tab (list, add/edit, delete, history)

## Phase 8: US7 — Check existing requests (P3)

- [X] T018 [US7] `GET /booking-rules/check`, `POST /booking-rules/rebook` + tests; UI section

## Phase 9: Polish

- [X] T019 `backend/scripts/eval_classification.py` (live, R1–R14 × Acme/Walmart)
- [X] T020 Tests, ruff, tsc/build, Postgres migration, live eval, rebuild stack
- [X] T021 [P] README section
