# Lio Procurement — Acme Corp case study

Delivers Acme Corp's three requests on the Lio procurement platform
(FastAPI + Next.js + PostgreSQL): reliable quote extraction, suggestions of
catalog articles at negotiated prices, and organization-specific booking rules.

The work follows spec-driven development with [GitHub Spec Kit](https://github.com/github/spec-kit):
every task has a spec (with the customer's answers to its open questions), a
plan backed by live experiments on the reference data, research notes, a data
model, API contracts, a quickstart and a task list under [`specs/`](specs/).

| Folder | What it holds |
| --- | --- |
| [`lio-procurement-app/`](lio-procurement-app/) | The application ([its README](lio-procurement-app/README.md) covers setup and architecture) |
| [`specs/`](specs/) | One folder per task: spec, plan, research, data model, contracts, quickstart, tasks |
| [`quotes/`](quotes/) | The five reference vendor quotes from Acme |
| [`.specify/`](.specify/) | Spec Kit templates and scripts; [`memory/constitution.md`](.specify/memory/constitution.md) holds the project principles |
| [`.claude/skills/`](.claude/skills/) | Spec Kit commands for Claude Code |

## Quick start

```bash
cd lio-procurement-app
cp .env.example .env          # set OPENAI_API_KEY=sk-... (no quotes, no spaces)
docker compose up --build     # app http://localhost:3200 · API http://localhost:7200/docs
```

Demo accounts (password `demo1234`): `admin@acme.com`, `buyer@acme.com`,
`requester@acme.com`, and `admin@walmart.com` for checking tenant isolation.

## Setup — Spec Kit and constitution

- Spec Kit installed for Claude Code (`.specify/`, `.claude/skills/`).
- [Constitution](.specify/memory/constitution.md): 11 principles taken from the existing code —
  tenant isolation, roles checked on the server, a layered backend, stable typed
  API contracts, per-organization configuration as validated settings, AI output
  checked in code, logged state changes, additive migrations, tests for every
  behaviour change, frontend conventions, simplicity.

## Task 1 — Reliable quote extraction · [`specs/001-reliable-quote-extraction`](specs/001-reliable-quote-extraction/)

**Asked:** extracted data is often wrong or empty, and uploads sometimes fail
(five reference quotes).

**Root causes found:** a `null` or `"$1,409.06"` broke the response schema and
the raw error was shown to users; PDF text came out with labels separated from
their values; the model was never told who the buyer was; there was no notion
of alternatives, discounts or a totals block; `.Pdf` files were rejected.

**Implemented**
- PDF text read in pypdf layout mode; one shared PDF check by type or `.pdf`
  name plus `%PDF-` bytes (`services/pdf.py`).
- OpenAI Structured Outputs into a nullable schema, bounded timeout and retries,
  plain-language failures with an `errorCode` (`services/extraction.py`).
- Rules in code (`services/quote_rules.py`): the buyer is never the vendor
  (org name + admin-managed `buyer_aliases`), only a 9-digit EIN is a tax ID,
  headings / alternatives / upsells are not order lines (incl. a priced row under
  an "Alternative…" heading), discounts kept, total cost = grand total, lines
  reconciled with totals within $0.02, per-field status (found / not in the
  quote / unreadable).
- Quote number, dates, totals breakdown and line discounts saved with the
  request (migration `0007`); department from the requester's profile;
  settings updates merge instead of replacing.
- New Request page: notes vs. warnings, discount-aware line maths, totals
  breakdown, read-only note for excluded alternatives.
- `.env.example`, one diagnostics log line per extraction, `scripts/eval_extraction.py`.

**Customer decisions:** total cost is the grand total; alternatives get a
read-only note; department comes from the requester's profile.

**Result:** 15/15 live runs, 100% correct on every field.

## Task 2 — Catalog articles at negotiated prices · [`specs/002-catalog-article-suggestions`](specs/002-catalog-article-suggestions/)

**Asked:** when a request is created, suggest matching catalog articles so the
negotiated prices are actually used.

**Design (from experiments):** a similarity threshold alone suggested
look-alikes (a real match scored 0.42, a trap 0.59), so embeddings shortlist
candidates and an LLM check confirms each is the same kind of item. Ranking,
units, savings, minimum order quantity and contracted-supplier recognition are
plain code (`services/catalog_matching.py`, `services/catalog_search.py`).

**Implemented**
- `POST /catalog/suggestions`: up to 3 agreements per line from the
  organization's own catalog, "Save $X" or "more expensive", cached and
  debounced; exact-word fallback without the AI service.
- New Request page: apply / undo / dismiss in one click, **Switch vendor** when
  the supplier differs, price-deviation and minimum-order notes,
  contracted-supplier badge and overcharge flag.
- Server-side agreement snapshot on order lines (migration `0008`): price copied
  from the catalog, articles of other organizations rejected, snapshot kept on
  later edits; unlinked lines store the best cheaper alternative and potential
  saving.
- Buyers see agreements used and missed savings on the request page and the
  approvals list; admins see agreement usage on the Articles page
  (`GET /catalog/usage`).
- `python -m app.embed_catalog` at startup (safe to re-run); `scripts/eval_suggestions.py`.

**Customer decisions:** warn and offer a one-click vendor switch (requests never
mix suppliers); no reason needed to ignore a cheaper agreement; an article's
quantity is its minimum order quantity.

**Result:** 22/22 reference lines correct, 95th-percentile lookup 0.92 s. Spec
Appendix R5/R10 corrected to follow the spec's own lowest-price ranking rule.

## Task 3 — Organization booking rules · [`specs/003-org-booking-rules`](specs/003-org-booking-rules/)

**Asked:** cable ties → Electrical Engineering, printer toner → IT Hardware,
small software subscriptions → Office Supplies — non-negotiable.

**Design (from experiments):** rules are deterministic include/exclude terms,
because embeddings scored "laser printer" above "TN-2420" against the toner
rule. Classification became its own step: choosing among 2,000 groups inside
the extraction call returned no group at all, while a shortlist of groups plus
a small model call returns a sensible one.

**Implemented**
- `booking_rules` with change history in `booking_rule_events` (migration
  `0009`); deterministic evaluation (`services/booking_rules.py`): wildcard
  terms, yearly amount limit, most specific rule wins, highest-value line decides
  mixed requests.
- Acme seeded with 11 · Electrical Engineering, 29 · Hardware, and
  15 · Office Equipment for subscriptions under $2,000 a year.
- `POST /classification` (`services/classification.py`): rules first, otherwise a
  system proposal; "Apply rule" hints for lines that only resemble a rule.
  Extraction uses the same step.
- Enforced on the server: requesters can't book a rule-covered request
  elsewhere; buyers and admins can override with a logged reason. Each request
  records how its group was decided.
- Organization → **Booking rules** tab: manage rules, history, check existing
  requests and re-book selected ones (`/booking-rules`, `/check`, `/rebook`).
- New Request page: rule explanation, locked selector for requesters,
  override-reason field, hints, split advice. `scripts/eval_classification.py`.

**Customer decisions:** "Office Supplies" doesn't exist, so the rule targets
15 · Office Equipment; "small" means under $2,000 a year; the highest-value
line decides.

**Also fixed:** commodity groups had been coming back empty since Task 1.

**Result:** 56/56 checks (scenarios R1–R14 × Acme and Walmart × runs); Walmart
is unaffected.

## Verification

- **210 backend tests**, offline — no network or API key (AI replaced by stubs).
- Frontend `tsc --noEmit` and `next build` pass.
- Migrations `0007`–`0009` checked on PostgreSQL 16 (upgrade, downgrade,
  re-upgrade); seeding is safe to re-run.
- No new ruff findings in changed files.
- Live evaluations (need `OPENAI_API_KEY`), from `lio-procurement-app/backend`:
  `python scripts/eval_extraction.py`, `eval_suggestions.py`, `eval_classification.py`.

## Trade-offs and next steps

- `gpt-4o-mini` everywhere; a first, uncached catalog lookup can take ~1.6 s.
- Rule terms are literal: a toner code without its hyphen ("TN2420") needs an
  admin-added term.
- A request created before the rules can't be edited by a requester until it
  is moved to its rule's group.
- Not done: the optional approval-threshold bonus; manual UI walkthroughs.
- Next: OCR for scanned PDFs, per-line commodity groups, catalog editing in the
  UI, keeping agreement snapshots when a catalog article is deleted.
