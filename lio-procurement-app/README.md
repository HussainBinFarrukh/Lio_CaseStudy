# Lio Procurement App

Upload vendor-offer PDFs, extract the details with AI, and track procurement
requests across your organization.

- **`frontend/`** — Next.js 15, React 19, Tailwind CSS 4
- **`backend/`** — FastAPI, SQLAlchemy, Alembic, JWT auth
- **Database** — PostgreSQL 16

## Prerequisites

- **Docker Desktop** (or Docker Engine) with **Docker Compose v2** — running before you start.
- An **OpenAI API key** is optional: the app boots and runs without it; only PDF extraction needs one.

## Quick start (Docker)

```bash
cp .env.example .env      # optional: add your OpenAI API key for PDF extraction
docker compose up --build
```

| | URL |
| --- | --- |
| App | http://localhost:3200 |
| API + docs | http://localhost:7200 · http://localhost:7200/docs |

Sign in with a demo account — no registration needed (password `demo1234`).
Development happens in the **Acme Corp** organization, which has one of each role:

| Account | Role | Can do |
| --- | --- | --- |
| `admin@acme.com` | admin | everything incl. members & settings |
| `buyer@acme.com` | buyer | approve requests |
| `requester@acme.com` | requester | create & track requests |

Every request needs approval by a buyer or admin (see the **Approvals** tab).

Other tenants exist to show the multi-tenant setup — **Walmart, Schaeffler,
Siemens, BMW** — each with an admin at `admin@<company>.com` (same password).
Their data is fully isolated from Acme's.

On startup the backend applies schema migrations and seeds the database (demo
accounts, organizations, commodity groups, suppliers) — both steps are
idempotent, so restarts never duplicate or overwrite anything (your data lives
in the `postgres_data` volume; `docker compose down -v` resets it). The OpenAI
key is only needed for PDF extraction — everything else works without it.

## Local development

```bash
docker compose up db        # Postgres only

# backend  → http://localhost:7200
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .
alembic upgrade head        # schema
python -m app.seed          # reference data (idempotent)
uvicorn app.main:app --reload --port 7200

# frontend → http://localhost:3200
cd frontend
npm install
npm run dev
```

## PDF extraction

`.env.example` lists every setting (`OPENAI_API_KEY`, `OPENAI_MODEL`,
`OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_RETRIES`, `JWT_SECRET`). Extraction reads
the PDF in layout order, asks the model for a fixed (Structured Outputs) schema,
then applies deterministic rules in `backend/app/services/quote_rules.py`:
the buyer is never the vendor, tax IDs must be a 9-digit EIN, alternatives /
headings / upsells are excluded from the order lines, discounts are kept, the
request total is the **grand total**, and lines are reconciled against the
quote's totals. Failures come back as plain-language messages with an
`errorCode`; each extraction logs one diagnostics line (no document text).

The names an organization appears under on quotes ("buyer aliases") are an
admin setting under **Organization → Settings**; Acme is seeded with
`ACME Corp`, `Lio Technologies, Inc.` and `askLio`.

## Catalog suggestions (negotiated prices)

While a request is built, each order line shows matching articles from the
organization's own catalog with supplier, negotiated price and the saving (or
extra cost) for the line's quantity; **Use this** applies one (undoable), and
the line then records the agreement it uses. Matching = embeddings retrieve the
closest catalog descriptions, then a small model confirms they are the *same
kind of item* (so "Desk organizer acrylic" is never suggested for an acrylic
logo); ranking, units, savings and minimum order quantities are plain code in
`backend/app/services/catalog_matching.py`. The catalog is embedded at startup
(`python -m app.embed_catalog`, idempotent); without `OPENAI_API_KEY`
suggestions fall back to exact-word matches. Buyers see unused cheaper
agreements on the request page and in Approvals; admins see agreement usage on
the Articles page.

## Commodity groups and booking rules

Each request's commodity group is decided in its own step once the order
lines are known: first the organization's **booking rules** (admin-managed
under **Organization → Booking rules**; Acme is seeded with cable ties →
Electrical Engineering, printer toner → Hardware, small software
subscriptions → Office Equipment), otherwise a **system proposal** (embeddings
shortlist the base groups, a small model picks one). Rules are deterministic
include/exclude terms with an optional yearly amount limit; the highest-value
line decides mixed requests. Requesters can't book a rule-covered request
elsewhere (enforced by the API); buyers and admins can, with a logged reason.
Lines that merely resemble a rule get an "Apply rule" hint instead of a silent
change. Admins can check existing requests against the rules and re-book them.

## Tests

```bash
cd backend && python -m pytest      # API + extraction tests (in-memory SQLite, no network)
cd frontend && npx tsc --noEmit && npm run build

# Live accuracy checks (need OPENAI_API_KEY):
cd backend && python scripts/eval_extraction.py --runs 3    # reference quotes in ../quotes
cd backend && python scripts/eval_suggestions.py --runs 3   # catalog suggestion scenarios
cd backend && python scripts/eval_classification.py --runs 3 # booking rules + classification
```

## Layout

```
backend/    FastAPI app — routers, services, models, schemas, core; Alembic migrations
frontend/   Next.js app — app-router pages, typed API client (src/lib/api), components
docker-compose.yml
```
