# Lio Procurement Platform Constitution

## Core Principles

### I. Tenant Isolation (NON-NEGOTIABLE)

Every organization is a separate customer and its data MUST be fully isolated.

- The caller's organization MUST be resolved server-side from
  `get_current_membership` (`app/core/deps.py`); a client-supplied organization ID MUST
  never be trusted.
- Every query over tenant-owned rows MUST filter on `organization_id ==
  membership.organization_id`. Single-row lookups MUST use a scoped helper in the style of
  `_get_org_request`, which returns **404** ("not found or you do not have permission") for
  another tenant's row, never 403 and never the row.
- Child rows without their own `organization_id` (order lines, activity, documents) MUST only
  be reached after a scope check on their parent request.
- Global reference data (the fixed `commodity_groups` taxonomy) is the only shared,
  non-tenant data. Anything a customer can customize MUST be org-scoped, not edited globally.
- New tenant-owned tables MUST carry an indexed `organization_id` FK with
  `ondelete="CASCADE"` and MUST ship with a cross-tenant isolation test.
- Behavior requested by one tenant (e.g. Acme Corp) MUST NOT change behavior for any other
  tenant (Walmart, Schaeffler, Siemens, BMW). Tenant names/slugs MUST NOT appear in
  application logic; only `app/seed.py` may reference them.

Rationale: leaking prices, suppliers, or requests between companies is a business-ending defect.

### II. Server-Enforced Role Authorization

Roles are `requester` < `buyer` < `admin`, enforced in the backend.

- Role checks MUST use FastAPI dependencies in `app/core/deps.py` (`require_buyer_or_admin`,
  `require_org_admin`); new role rules MUST be added there as new dependencies, not inlined
  in routers.
- Role values are constrained twice and MUST stay in sync: the DB `CheckConstraint`
  (`ck_org_member_role`) and the `MemberRole` `Literal` in schemas / TS types.
- Frontend role gating (`canApprove`, nav items in `DashboardNav`) is UX only, never a
  security boundary.
- Authorization changes MUST include tests for both the allowed and the forbidden role path.

Rationale: approval and pricing controls only matter if they cannot be bypassed via the API.

### III. Layered Backend Architecture

The backend keeps a strict, predictable layering; new code MUST follow it.

- `app/routers/` — HTTP concerns only: dependencies, scoping, request/response mapping,
  `HTTPException`s, transaction commit. One router per resource, registered in
  `create_app()` (`app/main.py`).
- `app/services/` — business logic and all external I/O (PDF parsing, OpenAI). Services
  MUST NOT depend on FastAPI request objects and MUST be callable from tests directly.
- `app/models/` — SQLAlchemy 2.x typed models (`Mapped[...]`), re-exported from
  `app/models/__init__.py`.
- `app/schemas/` — Pydantic v2 models for every request and response body.
- `app/core/` — config (`pydantic-settings` `settings`), security, dependencies.
- `app/data/` — static seed/reference datasets; no logic.
- Logic reused across endpoints MUST be extracted to a private helper (`_name`) or a
  service, not copy-pasted.

Rationale: the existing codebase is consistently layered; keeping it so makes changes
reviewable and testable in a 5-hour timebox.

### IV. Typed, Stable API Contract

The API contract is typed end-to-end and MUST NOT drift silently.

- Every endpoint MUST declare a `response_model` and accept a Pydantic schema, never raw
  dicts.
- Wire conventions MUST be preserved: request **inputs** use camelCase aliases
  (`Field(alias="vendorName")`); responses use snake_case matching DB rows; extraction
  payloads stay camelCase. Existing aliases (e.g. `titleShortDescription`,
  `commodity_groups`) are contract and MUST NOT be renamed without updating all consumers.
- Errors are `HTTPException` with a human-readable string `detail` (the frontend surfaces it
  via `ApiError`). Use the established status codes: 401 unauthenticated, 403 forbidden role,
  404 missing/other-tenant, 409 conflict/duplicate/already-decided, 410 expired,
  413 too large, 422 validation/business-rule failure.
- AI extraction returns its envelope `{success, data?, error?, missingFields?}` with HTTP 200
  so the UI can show partial results; it MUST NOT raise for model/parse failures.
- Any backend contract change MUST update the typed client and types in
  `frontend/src/lib/api/index.ts` (and `src/types/database.ts` where relevant) in the same
  change.

Rationale: the frontend is a thin typed consumer; contract drift breaks it at runtime, not
compile time.

### V. Tenant Configuration via Validated Settings

Customer-specific rules MUST be data, not code branches, and MUST be enforced
deterministically on the server.

- `OrganizationSettings` (JSON `organizations.settings`, `extra="forbid"`, `Literal`-typed
  fields) is the reference pattern: flexible storage, strictly validated at the edge. New
  per-tenant rules (commodity-group overrides, approval thresholds, etc.) MUST extend this
  pattern or add an org-scoped table — never hard-code a tenant.
- Settings MUST default to today's behavior so tenants that have not opted in are unaffected.
- Rules MUST be enforced in the backend on every write path (create AND update), in the
  style of `_enforce_required_fields`, and MUST be applied after any AI step; a prompt hint
  alone is insufficient.
- Only admins may change settings (`require_org_admin`); any member may read them.
- Catalog data (suppliers, articles with negotiated prices) is the source of truth for price
  suggestions; suggestions MUST come only from the requester's own organization's catalog.

Rationale: accounting and approval policies are contractual for the customer; probabilistic or
hard-coded behavior there is an audit and multi-tenancy risk.

### VI. Trustworthy AI Extraction

AI output is a suggestion that MUST be validated, recoverable, and reviewable.

- Prompts, model choice (`settings.openai_model`), and parsing MUST live in
  `app/services/extraction.py` / `app/services/pdf.py`, never in the frontend.
- LLM output MUST be parsed into typed schemas (`ExtractedVendorData`) with safe defaults;
  any reference it returns (e.g. `commodity_group_id`) MUST be validated against the DB and
  nulled if invalid.
- Numbers (totals, quantities, US number formats) MUST be normalized and cross-checked
  deterministically in code where possible, not trusted blindly.
- Fields that could not be extracted MUST be reported via `missingFields`; extracted data is
  shown to the user for review and correction before a request is created — extraction never
  auto-submits.
- The app MUST boot and every non-extraction feature MUST work without `OPENAI_API_KEY`.
- Uploads MUST be checked for PDF content type and the 10 MB `MAX_PDF_BYTES` limit; parse
  failures return a clean 422, not a 500.
- The five reference quotes in `/quotes` are the acceptance corpus: any change to PDF parsing
  or extraction MUST be verified against all five, with results noted in the PR.

Rationale: the customer's first complaint is unreliable extraction; reliability is measured on
their real documents.

### VII. Auditable State Changes

Every meaningful change to a procurement request MUST be recorded in its activity log.

- State-changing actions (create, field edits, status, approval, document attach, and any new
  automated decision such as auto-approval or rule-based recategorization) MUST write a
  `RequestActivity` row via `_log_activity` in the same transaction.
- Entries carry an `action` key, a human-readable `summary`, and structured `detail` (e.g.
  `changed_fields`, `from`/`to`). No-op updates MUST NOT log.
- `request_activity` is append-only; it MUST NOT be updated or deleted except by cascade with
  its request.
- Automated decisions MUST state why they happened (e.g. "Auto-approved: total below
  threshold", "Commodity group set by organization rule").

Rationale: approvals and bookings must be explainable to buyers, admins, and auditors.

### VIII. Data Integrity & Safe Evolution

The database enforces invariants, and schema changes MUST be safe on existing data.

- Enumerated columns MUST be backed by a DB `CheckConstraint` mirrored by a Pydantic
  `Literal` (as with `status`, `approval_status`, `role`).
- Money MUST use `Numeric(12, 2)` (quantities `Numeric(12, 3|4)`); never floats in storage.
- Primary keys are UUIDs (except fixed reference IDs); timestamps are timezone-aware via
  `TimestampMixin` / `CreatedAtMixin`; code uses `datetime.now(timezone.utc)`.
- All schema changes MUST be Alembic migrations in `backend/alembic/versions/`, numbered
  sequentially (`000N_description.py`), with a docstring explaining intent and a working
  `downgrade()`. Prefer additive changes (new tables, nullable columns, server defaults).
- Seeding (`app/seed.py`) MUST stay idempotent, keyed by natural keys (id, slug, email,
  name, article number); it inserts only missing rows and never overwrites user data.
- Code MUST be portable across PostgreSQL (prod) and SQLite (tests), e.g. JSONB via
  `with_variant(JSON(), "sqlite")`; no Postgres-only SQL without a test-safe path.

Rationale: the backend migrates and seeds on every startup; a non-idempotent or destructive
change corrupts every running environment.

### IX. Test-Backed Behavior Changes

Every behavior change MUST ship with automated tests that would fail without it.

- Backend tests live in `backend/tests/`, drive the real app through `TestClient` against
  in-memory SQLite (FKs enabled), and seed via the production `seed()` path.
- Tests MUST exercise behavior through the HTTP API; pure services MAY also be unit-tested.
- Each addressed customer complaint MUST have at least one regression test.
- AI-dependent code MUST be testable without network access (stub the OpenAI client or the
  service function); tests MUST NOT require `OPENAI_API_KEY`.
- Tests MUST be independent of execution order (use unique emails / fresh orgs per test).
- Frontend changes MUST pass `npx tsc --noEmit` and `npm run build`.
- Existing tests MUST keep passing; a test MAY only change when the behavior it encodes is
  intentionally changed, and the reason MUST be stated in the PR.

Rationale: the hand-off is judged on whether fixes demonstrably work without regressions.

### X. Frontend Conventions & Design System

The frontend MUST stay a thin, typed, consistent client of the backend.

- All backend calls MUST go through `@/lib/api` (`apiFetch` / `apiFetchObjectUrl`); pages
  MUST NOT call `fetch` against the API directly or handle tokens themselves.
- Pages live under the Next.js app router (`src/app/...`) as client components; shared UI
  primitives live in `src/components/base` and MUST be reused (`Button`, `Input`,
  `TextArea`, `Loader`, `Alert`) rather than re-implemented.
- Component variants use `class-variance-authority` and class merging uses `cn()` from
  `@/lib/utils`; formatting uses the shared helpers (`formatCurrency`, `formatDate`, ...).
- Styling MUST use the Tailwind design tokens in `globals.css` (`ink-*`, `accent*`,
  `canvas`, `surface`, `line`); no ad-hoc hex colors in components.
- Cached reference/server data SHOULD use TanStack Query (as in `useCommodityGroups`);
  mutations surface `ApiError.message` to the user.
- TypeScript `strict` mode MUST stay on; no `any` in new API types.

Rationale: consistency keeps the UI trustworthy and lets small changes stay small.

### XI. Simplicity, Value-First Scope & Transparent Hand-off

Work is timeboxed; deliver the most customer value and be explicit about the rest.

- Default priority unless a spec justifies otherwise: (1) extraction reliability,
  (2) negotiated-price/catalog suggestions, (3) commodity-group rules, (4) approval threshold.
- Prefer the simplest design that satisfies the spec (YAGNI) and extend existing patterns
  before inventing new ones. New dependencies, services, or infrastructure MUST be justified
  in the plan's Complexity Tracking.
- Code comments explain *why*, matching the existing style; no dead code or commented-out
  blocks.
- The pull request description is the hand-off and MUST state what changed, why, trade-offs,
  known limitations, and what would be done with more time.

Rationale: the customer and reviewers need to trust what shipped and know what did not.

## Technology & Platform Constraints

- **Backend**: Python ≥ 3.11, FastAPI, SQLAlchemy 2.x (typed ORM), Alembic, Pydantic v2 +
  pydantic-settings, `pypdf`, OpenAI SDK; lint with `ruff` (line length 100, py311).
- **Frontend**: Next.js 15 (app router, Turbopack), React 19, TypeScript strict, Tailwind CSS 4,
  TanStack Query 5, `class-variance-authority`, `clsx` + `tailwind-merge`.
- **Database**: PostgreSQL 16 (Docker); SQLite in-memory for tests.
- **Runtime**: `docker compose up --build` from `lio-procurement-app/` MUST start the full stack
  (app :3200, API :7200, docs :7200/docs) with no manual steps beyond an optional `.env`.
- **Configuration**: all config via environment variables read through `app/core/config.py`
  `settings`; no secrets in code or commits. `JWT_SECRET` defaults are for local dev only.
- **Security**: passwords hashed with bcrypt (`app/core/security.py`); JWT bearer auth via
  `get_current_user`; every non-auth endpoint requires authentication.
- **Data handling**: uploaded vendor PDFs are customer-confidential; they MUST NOT be logged
  in full or sent anywhere other than the configured extraction provider.

## Development Workflow & Quality Gates

- Work follows Spec-Driven Development: `/speckit-specify` → (`/speckit-clarify`) →
  `/speckit-plan` → `/speckit-tasks` → (`/speckit-analyze`) → `/speckit-implement`.
- Each feature is developed on a feature branch and merged to `main` via pull request.
- Every plan MUST pass the Constitution Check against Principles I–XI before design and again
  after design; violations MUST be justified in Complexity Tracking or removed.
- Merge gates (all MUST pass):
  1. `cd backend && python -m pytest`
  2. `cd backend && ruff check <changed files>` — no new findings in touched files (the
     existing baseline has pre-existing findings; fixing unrelated ones is out of scope).
  3. `cd frontend && npx tsc --noEmit && npm run build`
  4. Verification against the `/quotes` corpus for any extraction-related change.
  5. Reviewer confirms tenant scoping (I), role checks (II), and activity logging (VII) for
     any new or changed endpoint.
- Commits are small and descriptive; generated or local files (`node_modules`, `.venv`,
  `.env`, build output) are never committed.

## Governance

- This constitution supersedes conflicting conventions and ad-hoc practices in this
  repository. Runtime/setup guidance lives in `lio-procurement-app/README.md`.
- Amendments are made via `/speckit-constitution`, recorded in a PR with rationale, and MUST
  update the version and Last Amended date below.
- Versioning follows semantic versioning: MAJOR for removing or redefining a principle, MINOR
  for adding a principle/section or materially expanding guidance, PATCH for clarifications.
- Compliance is reviewed at plan time (Constitution Check) and at PR review; any accepted
  deviation MUST be documented in the PR description with its justification.

**Version**: 1.1.0 | **Ratified**: 2026-10-22 | **Last Amended**: 2026-10-22
