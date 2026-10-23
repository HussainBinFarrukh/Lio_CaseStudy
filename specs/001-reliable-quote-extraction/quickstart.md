# Quickstart: validating Reliable Vendor-Quote Extraction

How to prove the feature works. Contracts: [extraction-api.md](./contracts/extraction-api.md),
[requests-and-settings-api.md](./contracts/requests-and-settings-api.md). Expected values:
spec Appendices A & B (also `backend/tests/fixtures/reference_quotes.json`).

## Prerequisites

- Docker Desktop with Compose v2, or Python 3.11+ and Node 20+ for local runs.
- An OpenAI API key for the live checks (offline tests don't need one).

## 1. Configure

```bash
cd lio-procurement-app
cp .env.example .env          # set OPENAI_API_KEY; other values have defaults
docker compose up --build     # app :3200, API :7200
```

Expected: backend log shows migration `0007` applied and seed completing; restarting does not
duplicate or change data.

## 2. Offline automated checks (merge gate)

```bash
cd lio-procurement-app/backend && python -m pytest -q
cd lio-procurement-app/frontend && npx tsc --noEmit && npm run build
```

Expected: all pass **with no `OPENAI_API_KEY` set and no network**. Covers SC-009 (amount
parsing incl. `null` / `"1,234.56"`, EIN rules, buyer guard, position classification,
reconciliation, field status), error mapping for timeout / rate limit / refusal / truncation /
malformed output with no technical text (SC-006), PDF acceptance for `QuoteA0492_23.Pdf` and
empty MIME types, layout pairing on the five quotes, settings merge and membership checks.

## 3. Live reference evaluation (SC-001 – SC-004)

```bash
cd lio-procurement-app/backend
OPENAI_API_KEY=… python scripts/eval_extraction.py --quotes ../../quotes --runs 3
```

Expected: 15/15 runs without hard failure; per-field accuracy 100 % for vendor, tax ID, line
count & line totals (±0.02), net total and grand total. Record the table in the PR (constitution
VI).

## 4. Manual UI walkthrough (SC-005 – SC-008)

Sign in as `requester@acme.com` / `demo1234` → **New Request**. For each file in `quotes/`:

| Quote | Check |
| --- | --- |
| `QuoteA0492_23.Pdf` | Accepted despite `.Pdf`; vendor *Hollis Greenscapes*, tax ID `94-1985704`; exactly 2 lines (1,560.00 / 320.00); info notice "2 alternative items were not added: 1.1a, 1.1b"; total cost 2,042.15 |
| `QT-4120-Cust-14918.pdf` | Vendor *Greenmantle Moss Studio, LLC*, `85-3252405`; lines 715.26 (−20 %) and 622.00; shipping 215.00 in breakdown, not a line; total 1,686.14; change line 1 qty to 2 → 1,430.53 (discount kept) |
| `QT-OF2312380-Cust-57692.pdf` | Vendor *Bloomcraft Interiors, Inc.* (or verdeform), never Lio; info "No tax ID found in the quote"; 3 lines, no Moss Duo line; total 1,413.10 |
| `Quote_1__Lio_…2214703918.pdf` | Vendor Apple, `94-2404110`; 1 line 1,409.06; total 1,534.59 |
| `Quote_Hartwell_…Grinding_Machine.pdf` | Vendor *Hartwell Industrial Tools, Inc.* (not ACME); info "No tax ID…"; lines 15,000 / 2,000; total 18,402.50 |

For every quote: Department is the requester's profile department (or empty), never a contact
or "Attn" line; no reconciliation warning; the form is submittable without deleting lines or
fixing vendor/tax ID. After submitting, the request detail page shows quote number, dates and
the totals breakdown (Appendix B).

Failure path: stop network access / set an invalid key → upload shows the plain-language
message for the error code; no stack trace or exception text appears.

## 5. Settings

Sign in as `admin@acme.com` → Organization → Settings: aliases list shows the three seeded
names; add one, then toggle a required field → aliases are unchanged (FR-010). As
`buyer@acme.com` the settings cannot be changed (403).
