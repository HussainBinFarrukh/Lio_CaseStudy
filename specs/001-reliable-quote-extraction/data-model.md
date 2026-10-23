# Data Model: Reliable Vendor-Quote Extraction

**Feature**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

Three layers: **persisted** (DB, migration `0007`), **settings** (org JSON), and
**transient** (extraction pipeline, never stored). All changes are additive.

## 1. Persisted — migration `0007_quote_details`

### `procurement_requests` (existing table, new nullable columns)

| Column | Type | Null | Notes / validation |
| --- | --- | --- | --- |
| `quote_number` | `Text` | yes | As printed, trimmed (e.g. `A0492/23`). FR-028 |
| `quote_date` | `Date` | yes | FR-028 |
| `quote_valid_until` | `Date` | yes | Empty when not printed. FR-028 |
| `currency` | `String(3)` | yes | ISO 4217, upper-case; `USD` for all reference quotes. FR-020 |
| `net_total` | `Numeric(12,2)` | yes | Items subtotal before shipping/tax. FR-020 |
| `shipping_amount` | `Numeric(12,2)` | yes | Totals-block shipping only (table shipping is a line). |
| `tax_amount` | `Numeric(12,2)` | yes | All sales tax lines summed. |
| `fees_amount` | `Numeric(12,2)` | yes | Other document-level fees (e.g. eWaste). |

`total_cost` (existing, `Numeric(12,2)`) **semantics clarified**: the grand total
(FR-022). No column change.

Existing rows: all new columns `NULL` → UI shows "—". No backfill.

### `order_lines` (existing table, one new column)

| Column | Type | Null | Notes / validation |
| --- | --- | --- | --- |
| `discount_percent` | `Numeric(5,2)` | no, `server_default '0'` | 0 ≤ d < 100. `total_price` stays **net of discount**. FR-019 |

Invariant (checked, not enforced by DB): `total_price ≈ amount × unit_price × (1 − d/100)`
within 0.02 — violations surface as reconciliation warnings, never as rejections.

`downgrade()` drops the nine columns.

## 2. Settings — `organizations.settings` JSON (`OrganizationSettings`)

| Key | Type | Default | Validation |
| --- | --- | --- | --- |
| `required_fields` | `list[Literal["vat_id","department"]]` | `[]` | existing |
| `buyer_aliases` | `list[str]` | `[]` | ≤ 20 items; each trimmed, 1–120 chars; case-insensitive de-dupe; `extra="forbid"` still applies |

- **Write semantics**: `PATCH /organizations/me/settings` merges only the keys present in
  the payload (`exclude_unset`) into the stored dict (FR-010).
- **Seed**: Acme gets `["ACME Corp", "Lio Technologies, Inc.", "askLio"]` iff the key is
  absent. Other tenants: unchanged (`[]`).
- **Buyer names used by extraction** = `[organization.name] + buyer_aliases`.

## 3. Transient — extraction pipeline (`app/services/`)

```text
PDF bytes ──is_pdf_upload──▶ layout text ──LLM (LlmQuote)──▶ post-process ──▶ ExtractionResponse
                                              │                    │
                                   buyer names, model        buyer guard, EIN, positions,
                                                             totals, reconcile, field status
```

### `LlmQuote` (LLM-facing; Structured Outputs; all keys required, values nullable)

| Field | Type | Meaning |
| --- | --- | --- |
| `title` | `str \| null` | 2–5 word summary |
| `vendor_name` | `str \| null` | Issuer; legal entity preferred; never a buyer name |
| `vendor_tax_id` | `str \| null` | Raw value next to the issuer's EIN/Tax ID label |
| `quote_number`, `quote_date`, `valid_until` | `str \| null` | Dates as `YYYY-MM-DD` |
| `currency` | `str \| null` | ISO code |
| `positions` | `list[LlmPosition]` | Every item-table row, in order |
| `net_total`, `shipping`, `tax`, `fees`, `grand_total` | `number \| null` | Totals block |
| `commodity_group_id` | `int \| null` | From provided list |
| `absent_fields` | `list[Literal["vendor_name","vendor_tax_id","quote_number","quote_date","valid_until","net_total","shipping","tax","fees","grand_total"]]` | Fields not printed in the document |

### `LlmPosition`

| Field | Type | Notes |
| --- | --- | --- |
| `item_no` | `str \| null` | e.g. `1.1a` |
| `kind` | `"item" \| "alternative" \| "heading" \| "promotional"` | Model's classification |
| `description` | `str` | Incl. configuration bullets |
| `quantity` | `number \| null` | |
| `unit` | `str \| null` | Written out (`ea.` → `pieces`) |
| `unit_price` | `number \| null` | |
| `discount_percent` | `number \| null` | `-20.00%` → `20` |
| `line_total` | `number \| null` | As printed |
| `price_note` | `str \| null` | e.g. `U.P.` |

### Post-processing output (domain; mapped 1:1 to the API response)

- **OrderLine**: `description, quantity (default 1), unit, unit_price, discount_percent
  (default 0), line_total`. Kept iff classified `item` (rules: research R7).
- **ExcludedPosition**: `item_no, description, amount (unit_price or line_total), reason ∈
  {alternative, heading, promotional}`.
- **QuoteTotals**: `currency, net_total, shipping, tax, fees, grand_total`.
- **total_cost** = `grand_total` ?? (`net_total` ?? Σ line totals) + shipping + tax + fees
  (missing parts as 0).
- **ReconciliationFinding**: `scope ∈ {line, net_total, grand_total}, line_index?,
  expected, extracted` (tolerance 0.02; research R9).
- **FieldStatus**: map `field → extracted | not_in_document | could_not_extract` for
  `title, vendor_name, vat_id, department, order_lines, total_cost, commodity_group,
  quote_number, quote_date, valid_until`.

### State rules

| Condition | Result |
| --- | --- |
| Vendor matches a buyer name (normalised) | `vendor_name = ""`, status `could_not_extract` |
| Tax ID not exactly 9 digits after stripping | `vat_id = ""`, status `could_not_extract` (or `not_in_document` if model listed it absent) |
| Tax ID equals a buyer tax ID | cleared, `could_not_extract` |
| Value is `0` | `extracted` (never missing) |
| Department | from requester profile; `extracted` if non-empty, else not reported |
| All positions excluded | `order_lines = []`, info notice "No billable lines were identified" |
