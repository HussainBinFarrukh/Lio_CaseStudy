---

description: "Task list for Suggest Catalog Articles with Negotiated Prices"
---

# Tasks: Suggest Catalog Articles with Negotiated Prices

**Input**: Design documents from `/specs/002-catalog-article-suggestions/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Required (constitution IX; spec FR-025/FR-026).

**Paths** are relative to `lio-procurement-app/`.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

- [X] T001 [P] Settings `embedding_model`, `embedding_dimensions`, `suggestion_model`, `suggestion_timeout_seconds` in `backend/app/core/config.py`; pass-through in `docker-compose.yml` / `.env.example` not needed (defaults)
- [X] T002 [P] Ground truth `backend/tests/fixtures/catalog_reference.json` (Appendix A, R1–R11)

## Phase 2: Foundational

- [X] T003 Migration `backend/alembic/versions/0008_catalog_links.py` + model columns in `backend/app/models/article.py`, `backend/app/models/procurement_request.py`
- [X] T004 Schemas `backend/app/schemas/catalog.py` (suggestion in/out, verifier, usage)
- [X] T005 Pure rules `backend/app/services/catalog_matching.py`: unit normalisation, net unit price, comparison/saving, MOQ, ranking, contracted-supplier match
- [X] T006 I/O service `backend/app/services/catalog_search.py`: vector packing, per-org index, embed (cached), LLM verifier (cached, concurrent), lexical fallback, `suggest()` orchestration
- [X] T007 CLI `backend/app/embed_catalog.py` (idempotent, non-fatal) and run it in `backend/Dockerfile` after seed
- [X] T008 Frontend types/client in `frontend/src/lib/api/index.ts`, `frontend/src/types/database.ts`

## Phase 3: US1 — Suggestions while building a request (P1) 🎯 MVP

- [X] T009 [P] [US1] Rules tests (units, savings R1/R2/R3/R5/R9 to the cent, ranking toner R8) in `backend/tests/test_catalog_matching.py`
- [X] T010 [P] [US1] Service tests with stub embedder/verifier (traps rejected, empty catalog, fallback, cache) in `backend/tests/test_catalog_search.py`
- [X] T011 [US1] Router `backend/app/routers/catalog.py` `POST /catalog/suggestions`; register in `backend/app/main.py`; API tests incl. tenant isolation in `backend/tests/test_smoke.py`
- [X] T012 [US1] `frontend/src/components/CatalogSuggestions.tsx` + debounced per-line fetching in `frontend/src/app/dashboard/new-request/page.tsx`

## Phase 4: US2 — Apply in one action (P1)

- [X] T013 [US2] Link fields in `backend/app/schemas/requests.py`; server snapshot + foreign-article 422 + snapshot preserved on re-save in `backend/app/routers/requests.py`; API tests
- [X] T014 [US2] Apply/undo, deviation, MOQ note, vendor mismatch + **Switch vendor** in `frontend/src/app/dashboard/new-request/page.tsx`

## Phase 5: US5 — Relevant, not noisy (P2)

- [X] T015 [US5] Dismiss per line (reset on description change) in the New Request page; verifier "fewer rather than more" covered by T010

## Phase 6: US3 — Contracted suppliers (P2)

- [X] T016 [US3] Contracted supplier recognition + agreement check (R11) in services; tests; UI badge and overcharge note

## Phase 7: US4 — Buyers see agreement usage (P2)

- [X] T017 [US4] Store best unused alternative + `potential_saving` on create/update; `potential_saving_total`; activity summary; API tests
- [X] T018 [US4] Linked badges, alternatives and total in `frontend/src/app/dashboard/requests/[id]/page.tsx`; potential saving in `frontend/src/app/dashboard/approvals/page.tsx`

## Phase 8: US6 — Measurable (P3)

- [X] T019 [US6] `GET /catalog/usage` (admin) + tests; "Agreement usage" card in `frontend/src/app/dashboard/articles/page.tsx`

## Phase 9: Polish

- [X] T020 Live eval `backend/scripts/eval_suggestions.py` (R1–R11, latency)
- [X] T021 Run backend tests, ruff on changed files, `tsc` + `next build`, Postgres migration check, live eval
- [X] T022 [P] README section

## Dependencies

Setup → Foundational → US1 → US2 → US5 → US3 → US4 → US6 → Polish. US4/US6 depend on US2's
link columns.
