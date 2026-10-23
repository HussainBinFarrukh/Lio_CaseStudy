# Implementation Plan: Suggest Catalog Articles with Negotiated Prices

**Branch**: `002-catalog-article-suggestions` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-catalog-article-suggestions/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Show requesters the organization's negotiated catalog articles for every order line, let them
apply one in a click, and record agreement usage for buyers and admins. Technical approach
(see [research.md](./research.md), backed by two live experiments):

1. **Match** = embeddings retrieve (`text-embedding-3-small`@256, vectors stored per article,
   in-memory index per org) **+ LLM verification** ("same kind of item?", `gpt-4o-mini`,
   cached). Evidence: thresholds alone cannot separate matches (0.42) from traps (0.59); the
   verifier rejected every trap in the reference set at ~0.6 s median.
2. **Rank & compare** in deterministic code: relevance → lowest price → vendor/contracted
   supplier; units normalised; net-of-discount price; saving vs. "more expensive"; minimum
   order quantity note.
3. **Apply & record**: order lines gain a server-filled catalog snapshot and, for unlinked
   lines, the best unused cheaper alternative; vendor switch per FR-016.
4. **See it**: suggestions on New Request (debounced, never blocking), approval view with
   missed savings, admin usage report.
5. **Degrade gracefully**: no key / timeout → lexical exact-token matches; never an error.

## Technical Context

**Language/Version**: Python 3.11+ (image 3.12); TypeScript 5 strict

**Primary Dependencies**: FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, OpenAI SDK (≥1.92,
embeddings + `chat.completions.parse`); Next.js 15, React 19, TanStack Query 5. **No new
dependencies** (pure-Python cosine; no numpy/pgvector).

**Storage**: PostgreSQL 16; migration `0008_catalog_links` (article embedding columns, order-line
link + alternative snapshot columns)

**Testing**: pytest + TestClient on SQLite with stub embedder/verifier; `tsc` + `next build`;
live `scripts/eval_suggestions.py` (R1–R11, latency)

**Target Platform**: Docker Compose; browser SPA

**Project Type**: Web application (FastAPI + Next.js)

**Performance Goals**: suggestions ≤ 1 s p95 per line (SC-006) — embed ~30 ms, scan ~6 ms,
verify ~0.6 s median (cached thereafter); request creation never waits on suggestions in the UI

**Constraints**: org-scoped data only; AI failures invisible to users (FR-027); catalog
snapshot immutable after linking; no technical text in the UI

**Scale/Scope**: Acme catalog 1,920 articles / 393 unique descriptions / 120 suppliers; other
tenants empty; ~10 backend files, ~5 frontend files, 1 migration

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Pre | Post-design evidence |
| --- | --- | --- | --- |
| I | Tenant isolation | ✅ | Suggestions, usage and article validation filter on `membership.organization_id`; foreign `catalogArticleId` → 422; per-org in-memory index; caches keyed by org id; SC-007 test for all tenants. |
| II | Server-enforced roles | ✅ | Suggestions: any member; usage report: `require_org_admin`; approval view unchanged (buyer/admin). Tests for admin 200 / buyer 403. |
| III | Layered backend | ✅ | New `services/catalog_matching.py` (pure ranking/units/savings), `services/catalog_search.py` (embeddings, verifier, cache, fallback — all OpenAI I/O), `routers/catalog.py`; `app/embed_catalog.py` CLI mirrors `app/seed.py`. |
| IV | Typed, stable API | ✅ | New endpoints fully typed; request fields additive & optional; TS client updated. Suggestions response is camelCase like the extraction service it extends (both feed the New Request form) — consistent with the existing extraction exception. |
| V | Tenant config / catalog truth | ✅ | Prices and snapshots always read from the org's catalog server-side, never trusted from the client. |
| VI | Trustworthy AI | ✅ | AI only proposes; verifier output is structured (booleans); ranking/savings in code; user applies explicitly; fallback without key; reference set evaluated live. |
| VII | Auditable changes | ✅ | Creation summary includes agreement usage; link changes are order-line changes in the edit log. |
| VIII | Data integrity | ✅ | Additive migration with downgrade; `Numeric` money; `LargeBinary` works on SQLite and Postgres; embedding step idempotent (only missing/outdated vectors). |
| IX | Tests | ✅ | Offline tests with stubs for every story; SC-004 figures asserted to the cent. |
| X | Frontend conventions | ✅ | `@/lib/api` client, TanStack Query for suggestions (cache per line text), base components, tokens. |
| XI | Simplicity | ✅ | No new deps/infra; LLM only on ≤ 6 candidates per line, cached; logs instead of new tables for diagnostics. |

**Result**: PASS before and after design. No Complexity Tracking entries.

## Project Structure

### Documentation (this feature)

```text
specs/002-catalog-article-suggestions/
├── spec.md, plan.md, research.md, data-model.md, quickstart.md
├── contracts/catalog-api.md, contracts/requests-catalog-links.md
├── checklists/requirements.md
└── tasks.md            # /speckit-tasks
```

### Source Code

```text
lio-procurement-app/
├── backend/
│   ├── Dockerfile                                    # run app.embed_catalog after seed (non-fatal)
│   ├── alembic/versions/0008_catalog_links.py        # NEW
│   ├── app/
│   │   ├── core/config.py                            # embedding model/dims, suggestion timeouts
│   │   ├── embed_catalog.py                          # NEW — idempotent embedding CLI
│   │   ├── models/article.py, models/procurement_request.py   # new columns
│   │   ├── schemas/catalog.py                        # NEW — suggestion + usage schemas, verifier schema
│   │   ├── schemas/requests.py                       # link fields in/out, potential_saving_total
│   │   ├── services/catalog_matching.py              # NEW — units, comparison, ranking, MOQ, contracted supplier (pure)
│   │   ├── services/catalog_search.py                # NEW — embed, index, verify, cache, lexical fallback
│   │   ├── routers/catalog.py                        # NEW — /catalog/suggestions, /catalog/usage
│   │   ├── routers/requests.py                       # snapshot links, store alternatives, activity summary
│   │   └── main.py                                   # register router
│   ├── scripts/eval_suggestions.py                   # NEW — live R1–R11 + latency
│   └── tests/
│       ├── fixtures/catalog_reference.json           # NEW — Appendix A
│       ├── test_catalog_matching.py                  # NEW — pure rules, SC-004 figures
│       ├── test_catalog_search.py                    # NEW — stubbed embed/verify, fallback, caching
│       └── test_smoke.py                             # API: suggestions, links, 422, usage, isolation
└── frontend/src/
    ├── lib/api/index.ts                              # catalog client + types; link fields
    ├── types/database.ts                             # OrderLine link fields
    ├── components/CatalogSuggestions.tsx             # NEW — per-line suggestion list (apply/dismiss)
    ├── app/dashboard/new-request/page.tsx            # fetch, apply/undo, vendor switch, deviation, MOQ
    ├── app/dashboard/requests/[id]/page.tsx          # linked badges, alternatives, potential saving
    ├── app/dashboard/approvals/page.tsx              # potential saving column
    └── app/dashboard/articles/page.tsx               # admin "Agreement usage" card
```

**Structure Decision**: existing web-app layout; pure rules separated from I/O (as Task 1's
`quote_rules` vs `extraction`) so ranking and savings are testable without OpenAI.

## Delivery Order (timebox)

1. **P1 US1** suggestions (embed CLI + index + verifier + ranking + endpoint + UI list).
2. **P1 US2** apply/undo, server snapshot, vendor switch, deviation, MOQ.
3. **P2 US5** relevance safeguards (dismiss, fewer-not-more) — mostly covered by the verifier.
4. **P2 US3** contracted supplier + agreement check.
5. **P2 US4** stored alternatives + approval view.
6. **P3 US6** usage report.

Live eval after steps 1 and 6.

## Complexity Tracking

No violations.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
