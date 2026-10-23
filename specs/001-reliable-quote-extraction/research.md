# Phase 0 Research: Reliable Vendor-Quote Extraction

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-10-22

Evidence was gathered by reading the current code and by running `pypdf` 6.x over the five
reference quotes in `quotes/` (plain vs. layout text modes).

## Baseline: why extraction fails today

| Observed in code | Spec symptom |
| --- | --- |
| `ExtractedVendorData` fields are non-nullable (`vat_id: str = ""`, `unit_price: float = 0`); the LLM returns `null` (no tax ID) or `"$1,409.06"` → `ValidationError` → whole extraction fails with `str(exc)` shown to the user. | US1 hard failure + technical text (FR-001, FR-002, FR-005) |
| JSON mode is prompt-only ("Return ONLY valid JSON"), parsed with `json.loads` after stripping fences; no handling of refusal or `finish_reason == "length"`. | US1 (FR-003) |
| `OpenAI(...)` created with SDK defaults (600 s timeout); no app-level mapping of timeout / rate-limit errors. | US1 (FR-004, FR-005) |
| Frontend rejects files unless `file.type === 'application/pdf'`; backend checks `content_type` only; `QuoteA0492_23.Pdf` / empty MIME types are rejected. | US1 (FR-006) |
| `pdf.extract_text` uses pypdf **plain** mode: labels and values are emitted in separate runs (Apple: `Subtotal / Tax / … / Total` then the four amounts; Hollis: `333 571207 / 94 1985704` then `Permit No.: / EIN:`). | US2, US4 (FR-012) |
| Prompt asks for "Vendor/Supplier/Seller/Company name" and "Department/Customer/Bill To" without telling the model who the buyer is. | US2, US7 |
| Prompt has no notion of alternatives, headings, discounts or a totals block; `totalCost` is a single number. | US3, US4 |
| `missing_fields` uses truthiness (`not extracted.total_cost`), so `0` is "missing", and an absent tax ID is reported like an error. | US6 (FR-025, FR-026) |
| No `.env.example` exists, although the README says `cp .env.example .env`. | US1 scenario 6 (FR-007) |
| `PATCH /organizations/me/settings` stores `payload.model_dump()` — a full replace; the org page sends only `required_fields`. Any new setting would be wiped on save. | US2 scenario 6 (FR-010) |

## R1 — PDF text extraction mode

- **Decision**: Use `page.extract_text(extraction_mode="layout")`, then compress runs of 3+
  spaces to `" | "` (column separator) and drop blank lines. Fall back to plain mode for a
  page if layout mode raises. Keep `PdfReader(strict=False)` (default) so Hollis's broken xref
  table only logs a warning.
- **Rationale**: Verified on all five quotes: layout mode keeps label/value pairs on one line
  (`Permit No.: | 333 571207`, `EIN: | 94 1985704`, `Net total | $1,880.00`,
  `Grand total | $1,686.14`) and table rows intact
  (`1.1a | 1.00 | 00009 | As previous item… | $2,090.00 | U.P. | 24`,
  `2 | Moss Art Panel… | 1.00 | ea. | 894.08 | -20.00% | 715.26`). Satisfies FR-012
  without a new dependency. Cost: Hollis 0.9 s vs 0.1 s; others ≤ 0.03 s — negligible next to
  the LLM call (SC-010). Compressing whitespace roughly halves the extra tokens layout mode adds.
- **Alternatives considered**: `pdfplumber` / `pymupdf` (better tables, but a new dependency
  — constitution XI); sending the PDF/page images to a vision model (higher cost/latency;
  out of scope per spec); plain mode + more prompt instructions (can't recover pairing that
  is lost in the text).

## R2 — PDF acceptance (FR-006)

- **Decision**: One shared helper `is_pdf_upload(filename, content_type, head_bytes)` in
  `app/services/pdf.py`: accept when the declared type is a PDF type **or** the filename
  ends in `.pdf` (case-insensitive), **and** the content starts with `%PDF-` (allowing leading
  whitespace/BOM within the first 1 KB). Used by `POST /pdf/parse` and
  `PUT /requests/{id}/document`. Frontend: `accept=".pdf,application/pdf"` and a check on
  `type` **or** name suffix; the server is authoritative.
- **Rationale**: All five quotes start with `%PDF-`; browsers report `""` or
  `application/octet-stream` for some files; magic bytes are the reliable signal and reject
  renamed non-PDFs.
- **Alternatives considered**: `python-magic` (native dependency); trusting extension only
  (accepts non-PDFs).

## R3 — Guaranteed machine-readable LLM output (FR-001, FR-003)

- **Decision**: Use OpenAI **Structured Outputs** via
  `client.chat.completions.parse(response_format=LlmQuote)`. The dependency is unpinned
  (`openai>=1.54`), so Docker installs the latest SDK (3.37.0 at time of research, where
  `chat.completions.parse` is the GA location; the older `beta.chat.completions.parse` alias
  should not be relied on). Raise the lower bound in `pyproject.toml` to the first release that
  exposes `chat.completions.parse` (believed 1.92.0 — verify during implementation). Use a
  dedicated LLM-facing Pydantic schema `LlmQuote` (all fields
  required-but-nullable as Structured Outputs requires). Handle `message.refusal` and
  `finish_reason == "length"` explicitly. `LlmQuote` is internal to the service and distinct
  from the API response schema.
- **Rationale**: Schema-conformant JSON is guaranteed by the API for `gpt-4o-mini`; removes
  fence-stripping and `json.loads` failures. Nullable fields let the model say "absent"
  instead of inventing `""`/`0`.
- **Defense in depth (FR-002, SC-009)**: Amount/quantity fields on the internal domain model
  get `mode="before"` validators using a pure `parse_amount()` (`"$1,409.06"` → `1409.06`,
  `"1 409,06"` not supported/US only, `None` → `None`, `"-20.00%"` → `20.0` for discounts).
  Unit-tested offline; also protects against a future model/provider without strict schemas.
- **Alternatives considered**: JSON mode (`response_format={"type":"json_object"}`) — valid
  JSON but no schema guarantee; function calling — equivalent guarantee, more boilerplate.

## R4 — Timeouts, retries, user-facing errors (FR-004, FR-005, SC-006)

- **Decision**: Construct the client with `timeout=settings.openai_timeout_seconds` (default
  45) and `max_retries=settings.openai_max_retries` (default 2). The SDK retries
  connection errors, 408, 409, 429 and ≥500 with exponential backoff. Map failures to fixed,
  plain-language messages in the existing envelope (`success=false`, HTTP 200):

  | Cause | `errorCode` | Message to requester |
  | --- | --- | --- |
  | No API key configured | `not_configured` | "Automatic extraction isn't set up on this server. Please fill in the form manually or contact your administrator." |
  | Timeout / rate limit / connection / 5xx after retries | `service_busy` | "The extraction service is busy. Please try again in a minute." |
  | Refusal | `refused` | "This document couldn't be processed automatically. Please fill in the form manually." |
  | Truncated (`length`) | `too_long` | "This quote is too long to read automatically. Please fill in the form manually." |
  | No text in PDF / any other error | `unreadable` | "We couldn't read this quote automatically. Please fill in the form manually." |

  The technical exception is logged server-side with the `extractionId` (R10), never returned.
- **Rationale**: Uses SDK-native retry instead of custom loops (XI); the bounded worst case
  is ≈ 3 × 45 s plus backoff, under typical proxy limits. Codes let the UI and tests assert
  behavior without matching prose.
- **Alternatives considered**: `tenacity` (new dependency); background job + polling (out of
  scope per spec).

## R5 — Who is the buyer? (FR-008 – FR-010)

- **Decision**: Extend `OrganizationSettings` with
  `buyer_aliases: list[str]` (≤ 20 items, each 1–120 chars, trimmed, de-duplicated,
  default `[]`). The extraction endpoint resolves the caller's membership, loads org name +
  aliases, (a) passes them to the prompt ("the buyer is …; never return it as vendor"), and
  (b) applies a deterministic **buyer guard** afterwards: normalise names (casefold, strip
  punctuation and legal suffixes `inc|llc|ltd|corp|corporation|co|gmbh`, collapse spaces) and
  clear the vendor if it equals or contains / is contained in any buyer name → vendor status
  `could_not_extract`.
- **Settings PATCH semantics**: change to **merge** (`model_dump(exclude_unset=True)` over the
  stored dict) so saving one setting never resets another; the org page also gains a
  "Names your company appears under on quotes" editor.
- **Seed**: `app/seed.py` sets Acme's `buyer_aliases` to `["ACME Corp", "Lio Technologies,
  Inc.", "askLio"]` **only if the key is absent** (idempotent; never overwrites admin edits).
- **Extraction requires membership** (`get_current_membership`): needed to know the buyer;
  matches the spec's edge case. Users without an organization receive 403 like every other
  org-scoped endpoint.
- **Rationale**: Constitution V (tenant rules as validated settings, enforced server-side
  after the AI step), I (no tenant names in logic — only in seed).
- **Alternatives considered**: hard-coding the buyer names in the prompt (violates I/V);
  a new `organization_aliases` table (heavier; settings JSON is the reference pattern).

## R6 — Tax ID rules (FR-011)

- **Decision**: The prompt asks only for the value printed next to an EIN / Federal Tax ID /
  Tax ID / TIN label **of the issuer**. Post-processing: strip non-digits; accept only exactly
  9 digits → format `XX-XXXXXXX`; otherwise `null`. If it equals a buyer tax ID or the model
  reports two conflicting labelled IDs → `null` with status `could_not_extract`.
- **Rationale**: Deterministic normalisation fixes Hollis (`94 1985704` → `94-1985704`) and
  makes routing/account numbers (wrong length/label) unreturnable.

## R7 — Positions: lines vs. excluded (FR-013 – FR-017)

- **Decision**: The LLM returns **every** item-table row as a `position` with
  `kind ∈ {item, alternative, heading, promotional}` plus raw fields
  (`item_no, description, quantity, unit, unit_price, discount_percent, line_total,
  price_note`). Deterministic post-processing then decides:
  - `heading` or (no quantity **and** no unit price **and** no line total) → excluded `heading`;
  - `alternative`, or `price_note` matches `U.P.` / unit price present with no line total,
    or description matches `^(alt\.|alternative|option(al)?)\b|\(alt\.\)|instead of item` →
    excluded `alternative`;
  - `promotional` → excluded `promotional`;
  - a heading whose description equals the next item's description is dropped (no duplicate);
  - otherwise an order line; missing quantity → 1; printed `0.00` total is kept.
  Text outside the item table (T&C, notes, page subtotals, "Carried forward") is excluded by
  prompt instruction and by dropping rows with `kind` other than `item`.
- **Rationale**: The LLM is good at reading the table; the inclusion decision is auditable
  code (constitution VI) and unit-testable with recorded payloads for the five quotes.
- **UI**: excluded alternatives → one read-only `info` Alert ("2 alternative items were not
  added: 1.1a, 1.1b") (FR-018 clarified: no add-back). If every row is excluded → info
  "No billable lines were identified in this quote."

## R8 — Amounts and total cost (FR-019 – FR-022)

- **Decision**: Capture per line `discount_percent` (0–100, default 0) and `line_total`
  (net of discount). Capture document `currency` (ISO, default `USD`), `net_total`,
  `shipping`, `tax`, `fees`, `grand_total` — each nullable. **Total cost = grand total**
  (clarified): printed grand total if present, else `net (or Σ lines) + shipping + tax + fees`.
  In the form, editing a line recalculates `line_total = qty × unit_price × (1 − d/100)`
  (rounded to cents) and total cost = `Σ lines + shipping + tax + fees`.
- **Rationale**: Matches Appendix A (Greenmantle 715.26 with −20 %; Hollis grand 2,042.15).
- **Note**: Tax stays at the extracted amount when lines are edited (spec FR-022 wording);
  recomputing tax is out of scope.

## R9 — Reconciliation (FR-023, FR-024)

- **Decision**: Pure function `reconcile(lines, totals)` in the service returns findings
  `{scope: "line"|"net_total"|"grand_total", lineIndex?, expected, extracted}` using a
  tolerance of 0.02:
  - line: `|qty × unit × (1 − d) − line_total| > 0.02`;
  - net: Σ lines vs `net_total`, passing if either Σ or Σ + shipping matches (shipping printed
    as a table item vs. in the totals block);
  - grand: `net + shipping + tax + fees` vs `grand_total`.
  Returned in the extraction response; the form shows them as non-blocking `warning` text on
  the line/total and clears a line's finding once the requester edits that line.
- **Rationale**: Backend is the tested source of truth (IX); the UI only renders.

## R10 — Field status and diagnostics (FR-025, FR-026, FR-031, FR-032)

- **Decision**:
  - The LLM schema includes `absent_fields: list[...]` ("fields that are not printed in the
    document"). Post-processing assigns each reported field a status:
    value present → `extracted`; null and listed in `absent_fields` → `not_in_document`;
    otherwise (incl. cleared by buyer guard / invalid EIN) → `could_not_extract`.
    Presence uses `is not None`, so `0` is never missing (FR-026).
  - `missingFields` (existing contract) is kept and now lists **only** `could_not_extract`
    labels; new `fieldStatus` map carries all statuses; the UI shows `not_in_document` as an
    `info` note ("No tax ID found in the quote") and `could_not_extract` as a `warning`.
  - Every extraction gets a UUID `extractionId` (returned in the response) and one structured
    INFO log line: `extraction_id, organization_id, model, duration_ms, outcome/errorCode,
    line_count, excluded_count, field_status` — **no document text** (constitution data
    handling).
  - Repeatability: `temperature=0` and a fixed `seed`.
- **Alternatives considered**: persisting extraction runs in a table (more schema for a P3
  need; logs satisfy "logs or storage").

## R11 — Department (FR-027)

- **Decision**: Remove department from the LLM schema and prompt. The extraction service sets
  `department` from the caller's `Profile.department` (empty string if none); it is reported
  as `extracted` when set, otherwise omitted from warnings (it is not a quote field anymore).
- **Rationale**: Clarified answer; backend-side so it is testable and the UI just pre-fills.

## R12 — Quote metadata and persistence (FR-019, FR-020, FR-028, US8)

- **Decision**: Additive migration `0007_quote_details`:
  `procurement_requests` + nullable `quote_number`, `quote_date`, `quote_valid_until`
  (`Date`), `currency` (`String(3)`), `net_total`, `shipping_amount`, `tax_amount`,
  `fees_amount` (`Numeric(12,2)`); `order_lines` + `discount_percent`
  (`Numeric(5,2)`, `server_default '0'`). `RequestCreate`/`RequestUpdate` accept them as
  optional camelCase fields; `RequestUpdate` only changes them when present in the payload
  (`model_fields_set`) so the existing detail-page edit form cannot wipe them. Detail page
  shows quote reference + totals breakdown read-only. Dates are returned by the LLM as ISO
  `YYYY-MM-DD` (US `MM/DD/YY(YY)` normalised by the model; validated by Pydantic `date`).
- **Rationale**: Buyers need the values "with the request" (US8); additive & nullable per
  constitution VIII; existing requests and clients unaffected.

## R13 — Evaluation & tests (FR-029, FR-030, SC-001 – SC-009)

- **Decision**:
  - Ground truth for Appendices A & B as `backend/tests/fixtures/reference_quotes.json`.
  - **Offline pytest** (no network, no key): `parse_amount`, EIN normalisation, buyer guard,
    position classification, reconciliation, field status; PDF text tests for the five quotes
    (layout pairing, `.Pdf` acceptance, broken-xref file parses) — skipped if `quotes/` is not
    present (e.g. inside the Docker image); service tests with a **stubbed OpenAI client**
    returning recorded `LlmQuote` payloads per quote and asserting Appendix A lines/totals;
    error-mapping tests (timeout, rate limit, refusal, length, malformed) asserting no
    technical text; API tests for settings merge, alias validation, membership requirement.
  - **Live evaluation script** `backend/scripts/eval_extraction.py --runs 3`: runs the real
    pipeline on `quotes/`, compares with the fixture, prints per-field accuracy and
    hard-failure rate, exits non-zero below thresholds. Requires `OPENAI_API_KEY`; not part of
    pytest.
- **Existing tests intentionally changed** (reason stated per constitution IX):
  `test_extraction_without_api_key` — now signs in as an org member (extraction requires
  membership) and asserts `errorCode == "not_configured"` instead of the technical text
  `OPENAI_API_KEY` (FR-005). `test_org_settings_required_fields` — default settings now
  include `buyer_aliases: []`.

## R14 — Configuration template (FR-007)

- **Decision**: Add `lio-procurement-app/.env.example` listing `OPENAI_API_KEY`,
  `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_RETRIES`, `JWT_SECRET`, with
  comments; pass the two new variables through `docker-compose.yml`; README already
  references the file.

All Technical Context unknowns are resolved; no NEEDS CLARIFICATION remain.
