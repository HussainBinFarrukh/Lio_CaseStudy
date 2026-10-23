# Implementation Plan: Reliable Vendor-Quote Extraction

**Branch**: `001-reliable-quote-extraction` | **Date**: 2026-10-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-reliable-quote-extraction/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Make vendor-quote extraction reliable on the customer's five reference quotes. Technical
approach (see [research.md](./research.md)):

1. **Better input** — read PDFs in pypdf *layout* mode so labels stay paired with values and
   table rows stay intact; accept PDFs by type **or** `.pdf` name, verified by `%PDF-` bytes.
2. **Guaranteed output shape** — OpenAI Structured Outputs into an internal nullable
   `LlmQuote` schema that returns *every* table row with a classification, the totals block,
   quote metadata and which fields are absent from the document; bounded timeout + SDK retries;
   every failure mapped to a plain-language `errorCode`/message.
3. **Deterministic post-processing in code** — buyer guard (org name + admin-maintained
   `buyer_aliases` setting), EIN normalisation, line vs. excluded-position rules, discounts,
   totals (total cost = grand total), reconciliation (±$0.02) and per-field status.
4. **UI** — pre-filled form with discount-aware line maths, totals breakdown, quote reference,
   read-only notice for excluded alternatives, info vs. warning messages, reconciliation
   warnings, Department from the requester's profile; aliases editor in org settings.
5. **Proof** — offline pytest suite with stubbed LLM and recorded payloads for the five quotes,
   plus a live evaluation script reporting per-field accuracy over N runs.

## Technical Context

**Language/Version**: Python 3.11+ (Docker image 3.12); TypeScript 5 (strict)

**Primary Dependencies**: FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, pydantic-settings,
pypdf (layout mode), OpenAI SDK (`chat.completions.parse`, lower bound raised — research R3);
Next.js 15, React 19, TanStack Query 5, Tailwind 4. **No new dependencies.**

**Storage**: PostgreSQL 16; additive migration `0007_quote_details`; org settings JSON gains
`buyer_aliases`

**Testing**: pytest + FastAPI `TestClient` on in-memory SQLite, OpenAI client stubbed;
`tsc --noEmit` + `next build`; live `scripts/eval_extraction.py` (needs key, not in CI)

**Target Platform**: Docker Compose (Linux containers); browser SPA

**Project Type**: Web application (FastAPI backend + Next.js frontend)

**Performance Goals**: Median upload → pre-filled form ≤ today's median + ~10 % (SC-010);
layout parsing adds ≤ 1 s on the largest reference quote

**Constraints**: Extraction bounded (45 s timeout × up to 3 attempts); no technical text to
users; no full document text in logs; existing requests/clients keep working; works without
`OPENAI_API_KEY` (extraction reports `not_configured`)

**Scale/Scope**: 5 reference quotes (1–2 pages each); ~10 backend files, ~5 frontend files,
1 migration; 5-hour case-study timebox → P1 stories first

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Pre-design | Post-design evidence |
| --- | --- | --- | --- |
| I | Tenant isolation | ✅ | Extraction now resolves org via `get_current_membership`; buyer names come only from the caller's org; aliases live in that org's settings; no tenant names in logic (Acme aliases only in `seed.py`). |
| II | Server-enforced roles | ✅ | Aliases edited via existing admin-only `PATCH /organizations/me/settings`; tests for admin 200 / buyer 403. |
| III | Layered backend | ✅ | `services/pdf.py` (text + `is_pdf_upload`), `services/extraction.py` (LLM I/O, error mapping), new pure `services/quote_rules.py` (guard, EIN, positions, totals, reconcile, status); routers stay thin. |
| IV | Typed, stable API | ✅ | Additive camelCase fields; existing keys unchanged; envelope + HTTP 200 for extraction failures; TS client updated in same change. One intentional behavior change documented (membership required for `/extraction`). |
| V | Tenant config via validated settings | ✅ | `buyer_aliases` on `OrganizationSettings` (`extra="forbid"`, bounded); default `[]` = today's behavior; guard applied in code after the AI step; PATCH becomes merge. |
| VI | Trustworthy AI extraction | ✅ | Structured Outputs; nullable schema; deterministic normalisation/cross-checks; review before submit; works without key; PDF checks; `/quotes` corpus evaluated live and offline. |
| VII | Auditable state changes | ✅ | Extraction itself changes no request state; request creation/edit logging unchanged and extended to new fields. |
| VIII | Data integrity & safe evolution | ✅ | Migration `0007` additive (nullable columns, `server_default '0'`), working downgrade; `Numeric` money; seed idempotent (alias set only if absent); SQLite-portable. |
| IX | Test-backed changes | ✅ | Offline tests per complaint; LLM stubbed. Two existing tests intentionally changed — reasons in research R13. |
| X | Frontend conventions | ✅ | Calls via `@/lib/api`; `Alert` (`info`/`warning`) and base `Input`/`Button` reused; tokens only; strict TS. |
| XI | Simplicity & hand-off | ✅ | No new dependencies/services; SDK retries over custom loops; logs over a new diagnostics table; P1 → P3 ordering for the timebox. |

**Result**: PASS (pre- and post-design). No Complexity Tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/001-reliable-quote-extraction/
├── plan.md              # This file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── extraction-api.md
│   └── requests-and-settings-api.md
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
quotes/                                   # reference corpus (read by tests & eval script)
lio-procurement-app/
├── .env.example                          # NEW — FR-007
├── docker-compose.yml                    # pass OPENAI_TIMEOUT_SECONDS / OPENAI_MAX_RETRIES
├── backend/
│   ├── pyproject.toml                    # raise openai lower bound
│   ├── alembic/versions/0007_quote_details.py          # NEW
│   ├── app/
│   │   ├── core/config.py                # openai_timeout_seconds, openai_max_retries
│   │   ├── models/procurement_request.py # quote/total columns, discount_percent
│   │   ├── schemas/extraction.py         # API response models (additive) + LlmQuote/LlmPosition
│   │   ├── schemas/requests.py           # optional quote fields, discountPercent, RequestOut
│   │   ├── schemas/organizations.py      # buyer_aliases
│   │   ├── services/pdf.py               # layout text, is_pdf_upload
│   │   ├── services/extraction.py        # prompt, Structured Outputs, retries, error mapping, logging
│   │   ├── services/quote_rules.py       # NEW — pure post-processing rules
│   │   ├── routers/extraction.py         # membership dependency, buyer names, profile department
│   │   ├── routers/pdf.py                # shared PDF acceptance
│   │   ├── routers/requests.py           # persist new fields, PDF acceptance, activity labels
│   │   ├── routers/organizations.py      # settings merge
│   │   └── seed.py                       # Acme buyer_aliases if absent
│   ├── scripts/eval_extraction.py        # NEW — live evaluation (FR-029)
│   └── tests/
│       ├── fixtures/reference_quotes.json          # NEW — Appendices A & B
│       ├── fixtures/llm_payloads/*.json            # NEW — recorded LlmQuote per quote
│       ├── test_quote_rules.py                     # NEW — pure rules
│       ├── test_extraction_service.py              # NEW — stubbed LLM, error mapping
│       ├── test_pdf_quotes.py                      # NEW — layout text & acceptance on quotes/
│       └── test_smoke.py                           # 2 tests updated; settings merge + membership tests
└── frontend/src/
    ├── lib/api/index.ts                  # types for new fields
    ├── app/dashboard/new-request/page.tsx            # file accept, notices, discount maths, totals, quote ref, profile dept
    ├── app/dashboard/requests/[id]/page.tsx          # show quote ref + totals breakdown; keep discount on edit
    └── app/dashboard/organization/page.tsx           # buyer aliases editor
```

**Structure Decision**: Existing web-app layout (`lio-procurement-app/backend` +
`lio-procurement-app/frontend`); new code follows constitution III layering. Only one new
backend module (`services/quote_rules.py`) — pure functions, so the rules are unit-testable
without FastAPI or OpenAI.

## Delivery Order (timebox guidance for `/speckit-tasks`)

1. **P1 — US1 robustness**: PDF acceptance, layout text, Structured Outputs + nullable schema,
   amount parsing, timeout/retry, error mapping, `.env.example`.
2. **P1 — US2 vendor/tax ID**: `buyer_aliases` setting (+ merge PATCH, seed, UI), membership
   on `/extraction`, buyer guard, EIN rules.
3. **P1 — US3 lines**: position classification, excluded positions, read-only notice.
4. **P2 — US4/US5/US6**: discounts, totals breakdown & grand-total cost, reconciliation,
   field status (info vs warning).
5. **P3 — US7/US8/US9**: profile department, quote metadata persistence (migration 0007,
   detail page), eval script & diagnostics logging.

Each step ends with offline tests green; the live eval runs after steps 3 and 5.

## Complexity Tracking

No constitution violations — table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
