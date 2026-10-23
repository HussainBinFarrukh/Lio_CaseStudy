---

description: "Task list for Reliable Vendor-Quote Extraction"
---

# Tasks: Reliable Vendor-Quote Extraction

**Input**: Design documents from `/specs/001-reliable-quote-extraction/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Required — constitution IX and spec FR-029/FR-030/SC-009 mandate offline tests.

**Organization**: Grouped by user story; paths relative to `lio-procurement-app/` unless they
start with `quotes/` or `specs/`.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 [P] Create configuration template `.env.example` (OPENAI_API_KEY, OPENAI_MODEL, OPENAI_TIMEOUT_SECONDS, OPENAI_MAX_RETRIES, JWT_SECRET) and pass the two new variables in `docker-compose.yml` (FR-007)
- [X] T002 [P] Raise the `openai` lower bound in `backend/pyproject.toml` to a release exposing `chat.completions.parse` (research R3)
- [X] T003 [P] Add `openai_timeout_seconds` (45) and `openai_max_retries` (2) to `backend/app/core/config.py`
- [X] T004 [P] Create ground-truth fixture `backend/tests/fixtures/reference_quotes.json` from spec Appendices A & B

---

## Phase 2: Foundational (Blocking Prerequisites)

- [X] T005 Define internal LLM schemas `LlmPosition`, `LlmQuote` and additive API response models (`OrderLineData.discount_percent`, `QuoteTotals`, `ExcludedPosition`, `ReconciliationFinding`, `field_status`, `error_code`, `extraction_id`, quote metadata) in `backend/app/schemas/extraction.py`
- [X] T006 Create `backend/app/services/numbers.py` with `parse_amount`/`parse_percent` (FR-002) used by schema `mode="before"` validators (separate module avoids a schemas ↔ quote_rules import cycle); pure rules module `backend/app/services/quote_rules.py`
- [X] T007 Extend `frontend/src/lib/api/index.ts` types per contracts/extraction-api.md and contracts/requests-and-settings-api.md

**Checkpoint**: schemas + rules skeleton in place.

---

## Phase 3: User Story 1 — Uploading a quote never fails outright (P1) 🎯 MVP

**Independent Test**: each quote uploads 3× to a pre-filled form; no technical text.

### Tests

- [X] T008 [P] [US1] `backend/tests/test_quote_rules.py`: `parse_amount` (`"$1,409.06"`, `None`, `"1,234.56"`, ints), quantity default 1
- [X] T009 [P] [US1] `backend/tests/test_pdf_quotes.py`: all five `quotes/` parse (incl. broken-xref Hollis), layout text pairs `EIN: | 94 1985704` and `Grand total | $2,042.15`; `is_pdf_upload` accepts `.Pdf` / empty / octet-stream types with `%PDF-`, rejects non-PDF content (skip if `quotes/` missing)
- [X] T010 [P] [US1] `backend/tests/test_extraction_service.py`: stubbed client — timeout, rate limit, connection error, refusal, `length`, invalid output, missing key → `success=false`, correct `errorCode`, message without exception text

### Implementation

- [X] T011 [US1] Layout-mode text with ` | ` column compression and per-page plain fallback; `is_pdf_upload()` in `backend/app/services/pdf.py`
- [X] T012 [US1] Use `is_pdf_upload` and friendly 422 in `backend/app/routers/pdf.py` and `PUT /requests/{id}/document` in `backend/app/routers/requests.py` (FR-006)
- [X] T013 [US1] Rewrite `backend/app/services/extraction.py`: Structured Outputs via `chat.completions.parse(response_format=LlmQuote)`, `temperature=0`, fixed `seed`, timeout/retries from settings, refusal/length handling, `errorCode` → plain message mapping (research R4), `extractionId`
- [X] T014 [US1] Frontend file acceptance (`accept=".pdf,application/pdf"`, type **or** name check) and error display in `frontend/src/app/dashboard/new-request/page.tsx`

---

## Phase 4: User Story 2 — Vendor and tax ID identified correctly (P1)

**Independent Test**: vendor/tax ID match Appendix A for all five quotes.

### Tests

- [X] T015 [P] [US2] Rules tests: buyer-name normalisation/guard (Lio Technologies, Inc. / ACME Corp / askLio), EIN normalisation (`94 1985704` → `94-1985704`, 8/10 digits → empty, buyer EIN → empty) in `backend/tests/test_quote_rules.py`
- [X] T016 [P] [US2] API tests in `backend/tests/test_smoke.py`: settings merge (aliases survive `required_fields` save and vice versa), alias validation 422, buyer 403, `/extraction` requires membership; update `test_org_settings_required_fields` default-settings assertion (reason: new `buyer_aliases` key)

### Implementation

- [X] T017 [US2] `buyer_aliases` on `OrganizationSettings` with validation in `backend/app/schemas/organizations.py`
- [X] T018 [US2] Merge semantics for `PATCH /organizations/me/settings` in `backend/app/routers/organizations.py` (FR-010)
- [X] T019 [US2] Seed Acme `buyer_aliases` iff absent in `backend/app/seed.py`
- [X] T020 [US2] `normalize_company`, `is_buyer`, `normalize_ein` in `backend/app/services/quote_rules.py`
- [X] T021 [US2] `/extraction` uses `get_current_membership`, passes buyer names to the service in `backend/app/routers/extraction.py`; prompt rules for issuer vs recipient and tax ID labels in `backend/app/services/extraction.py`
- [X] T022 [US2] Buyer-aliases editor in Settings tab of `frontend/src/app/dashboard/organization/page.tsx`

---

## Phase 5: User Story 3 — Order lines contain only what is bought (P1)

**Independent Test**: lines match Appendix A; alternatives listed in a read-only notice.

### Tests

- [X] T023 [P] [US3] Classification tests (heading, `U.P.`, "Alternative", "(Alt.)", promotional, duplicate heading, printed 0.00 kept) in `backend/tests/test_quote_rules.py`
- [X] T024 [P] [US3] Recorded LLM payloads per reference quote in `backend/tests/fixtures/llm_payloads.json`; service test asserting Appendix A lines and excluded positions with stubbed client in `backend/tests/test_extraction_service.py`

### Implementation

- [X] T025 [US3] `classify_positions()` → order lines + excluded positions in `backend/app/services/quote_rules.py`
- [X] T026 [US3] Prompt: return every table row with `kind`, `price_note`; exclude non-table text in `backend/app/services/extraction.py`
- [X] T027 [US3] Read-only info notice for excluded alternatives and "no billable lines" in `frontend/src/app/dashboard/new-request/page.tsx`

---

## Phase 6: User Story 4 — Amounts, discounts, totals (P2)

### Tests

- [X] T028 [P] [US4] Totals/total-cost tests (grand total preferred; fallback sum) in `backend/tests/test_quote_rules.py`

### Implementation

- [X] T029 [US4] `compute_total_cost()` and discount-aware lines in `backend/app/services/quote_rules.py`; map `totals`, `discountPercent`, `totalCost` (grand) in `backend/app/services/extraction.py`
- [X] T030 [US4] Discount-aware line maths, totals breakdown, total cost = Σ lines + shipping + tax + fees in `frontend/src/app/dashboard/new-request/page.tsx`

---

## Phase 7: User Story 5 — Totals cross-checked (P2)

- [X] T031 [P] [US5] Reconciliation tests (line mismatch, net with/without shipping, grand, all-pass) in `backend/tests/test_quote_rules.py`
- [X] T032 [US5] `reconcile()` in `backend/app/services/quote_rules.py`, included in extraction response
- [X] T033 [US5] Non-blocking warnings on affected line/total, cleared on line edit, in `frontend/src/app/dashboard/new-request/page.tsx`

---

## Phase 8: User Story 6 — Missing data reported honestly (P2)

- [X] T034 [P] [US6] Field-status tests (`0` extracted; absent tax ID → `not_in_document`; buyer-cleared vendor → `could_not_extract`; `missingFields` only lists `could_not_extract`) in `backend/tests/test_quote_rules.py`
- [X] T035 [US6] `field_statuses()` in `backend/app/services/quote_rules.py`; `missingFields` + `fieldStatus` in `backend/app/services/extraction.py`
- [X] T036 [US6] Info notes vs. warnings in `frontend/src/app/dashboard/new-request/page.tsx`

---

## Phase 9: User Story 7 — Department not filled with customer name (P3)

- [X] T037 [US7] Remove department from LLM schema/prompt; set from requester `Profile.department` in `backend/app/routers/extraction.py`; test in `backend/tests/test_smoke.py`

---

## Phase 10: User Story 8 — Quote reference data captured (P3)

- [X] T038 [US8] Migration `backend/alembic/versions/0007_quote_details.py` + model columns in `backend/app/models/procurement_request.py`
- [X] T039 [US8] Optional quote fields & `discountPercent` in `RequestCreate`/`RequestUpdate`/`RequestOut` (`backend/app/schemas/requests.py`); persist + update-only-if-set + activity labels in `backend/app/routers/requests.py`
- [X] T040 [P] [US8] API test: create with quote fields, edit without them keeps values, discount persisted, in `backend/tests/test_smoke.py`
- [X] T041 [US8] Quote reference inputs on new-request page; read-only quote reference & totals breakdown on `frontend/src/app/dashboard/requests/[id]/page.tsx`, keeping `discountPercent` on edit

---

## Phase 11: User Story 9 — Measurable and diagnosable (P3)

- [X] T042 [US9] Structured INFO log per extraction (id, org, model, duration, outcome, counts, field status; no document text) in `backend/app/services/extraction.py`
- [X] T043 [US9] Live evaluation script `backend/scripts/eval_extraction.py` (N runs, per-field accuracy, hard-failure rate, non-zero exit below threshold)
- [X] T044 [US9] Update `test_extraction_without_api_key` in `backend/tests/test_smoke.py` (reason: membership required + no technical text, FR-005)

---

## Phase 12: Polish & Cross-Cutting

- [X] T045 Run backend suite, ruff on changed files, `tsc --noEmit` + `next build`
- [X] T046 [P] README: configuration template, eval script, buyer aliases
- [ ] T047 Run quickstart.md validation — offline steps done (100 tests, tsc, build, Postgres migration); live eval (step 3) passed 15/15 runs at 100% on every field (gpt-4o-mini, 2026-10-23); manual UI walkthrough (step 4) still pending

---

## Dependencies & Execution Order

- Setup → Foundational → US1 → US2 → US3 → US4 → US5 → US6 → US7 → US8 → US9 → Polish.
- US2–US6 all extend `quote_rules.py` and `extraction.py` (same files → sequential).
- US8 migration is independent of US1–US7 and can run in parallel with them.
- Frontend tasks depend on T007 types.

## Implementation Strategy

MVP = Phases 1–5 (all P1 stories) with offline tests green; then P2 (US4–US6); then P3
(US7–US9). Live evaluation after US3 and at the end.
