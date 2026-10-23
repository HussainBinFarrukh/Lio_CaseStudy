# Data Model: Suggest Catalog Articles with Negotiated Prices

**Feature**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

All changes are additive (migration `0008_catalog_links`); existing rows stay valid.

## 1. Persisted

### `articles` (existing, org-scoped) — new nullable columns

| Column | Type | Notes |
| --- | --- | --- |
| `embedding` | `LargeBinary` | 256 × float32, L2-normalised (1 KB). `NULL` = not embedded yet. |
| `embedding_model` | `String` | e.g. `text-embedding-3-small@256`; a different value means "re-embed". |

### `order_lines` (existing) — catalog link snapshot (FR-013, FR-014)

| Column | Type | Notes |
| --- | --- | --- |
| `catalog_article_id` | `Uuid` FK `articles.id`, `ON DELETE SET NULL`, indexed | Set only by the server after verifying the article belongs to the request's organization. |
| `article_number` | `Text` | Snapshot at linking time. |
| `article_description` | `Text` | Snapshot. |
| `article_supplier_name` | `Text` | Snapshot. |
| `negotiated_unit_price` | `Numeric(12,2)` | Snapshot of the catalog price (never client-supplied). |
| `article_min_quantity` | `Numeric(12,3)` | Snapshot of the article's minimum order quantity (FR-024). |
| `original_unit_price` | `Numeric(12,2)` | The line's unit price before the article was applied (quote price) — basis for realised savings. |

Derived (not stored): **deviation** = `unit_price − negotiated_unit_price` (FR-014);
**linked** = `article_number IS NOT NULL` (survives article deletion).

### `order_lines` — best unused alternative (FR-019 – FR-022)

| Column | Type | Notes |
| --- | --- | --- |
| `alternative_article_number` | `Text` | Cheapest confirmed, comparable, *cheaper* catalog article for an unlinked line, at create/update time. |
| `alternative_supplier_name` | `Text` | |
| `alternative_unit_price` | `Numeric(12,2)` | |
| `potential_saving` | `Numeric(12,2)` | `(line net unit price − alternative price) × quantity`, > 0. |

All `NULL` for linked lines and lines without a cheaper alternative.

## 2. Transient (suggestion service)

```text
line description ─embed (cache)─▶ cosine vs org index (unique descriptions) ─▶ top 6
      ─verify (LLM, cache) ─▶ confirmed ─▶ rank ─▶ compare (units, net price, MOQ) ─▶ top N
            └── on failure / no key: lexical fallback (research R7)
```

### `SuggestionLineIn`
`key` (client id), `description`, `unit`, `quantity`, `unitPrice`, `discountPercent`,
`totalPrice`, `currency`.

### `ArticleSuggestion`
| Field | Notes |
| --- | --- |
| `articleId`, `articleNumber`, `description`, `supplierId`, `supplierName`, `unitPrice`, `unit`, `currency`, `minQuantity` | From the org's catalog. |
| `relevance` | Similarity score (for ordering only). |
| `comparable` | `true` when units match and currencies are USD and the line has a price. |
| `unitDifference` | `unitPrice − line net unit price` (only if comparable). |
| `lineEffect` | `unitDifference × quantity`; `< 0` saving, `> 0` more expensive. |
| `belowMinQuantity` | `minQuantity > line quantity`. |
| `fromVendor` | Article supplier = request vendor / contracted supplier. |

### `LineSuggestions`
`key`, `suggestions: ArticleSuggestion[]` (≤ limit), `agreementCheck?` (`articleNumber`,
`negotiatedPrice`, `difference`) when the contracted supplier's own article is cheaper (US3).

### `SuggestionsResponse`
`contractedSupplier? {id, name}`, `lines: LineSuggestions[]`, `source: "semantic" | "lexical"`.

### State rules

| Condition | Result |
| --- | --- |
| Empty description, empty catalog | no lookup / empty list |
| Units differ (piece vs sq ft) | suggestion shown, `comparable=false`, no saving figure, unit note |
| Article more expensive | `lineEffect > 0` → "more expensive by …" |
| Article min qty > line qty | `belowMinQuantity=true` → note |
| AI unavailable | lexical fallback; never an error |
| Linked line price ≠ negotiated | deviation shown and stored (derived) |
| Linked supplier ≠ request vendor | `supplierMismatch` flag in UI and buyer view |

## 3. Reporting (US6) — computed on demand

Per organization and period (`created_at` of requests):

| Metric | Definition |
| --- | --- |
| `lineCount`, `linkedLineCount`, `linkedShare` | Order lines of the org's requests; linked = `article_number` set. |
| `realisedSavings` | Σ over linked lines with `original_unit_price`: `(original − negotiated) × amount` (positive part). |
| `missedSavings` | Σ `potential_saving` over unlinked lines. |
