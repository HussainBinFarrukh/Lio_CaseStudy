# Contract: Requests & organization settings (additive changes)

## `POST /requests` and `PUT /requests/{id}`

New **optional** input fields (camelCase aliases, constitution IV):

| Field | Type | Maps to |
| --- | --- | --- |
| `quoteNumber` | `string \| null` | `quote_number` |
| `quoteDate` | `YYYY-MM-DD \| null` | `quote_date` |
| `validUntil` | `YYYY-MM-DD \| null` | `quote_valid_until` |
| `currency` | `string(3) \| null` | `currency` (upper-cased) |
| `netTotal`, `shippingAmount`, `taxAmount`, `feesAmount` | `number \| null`, ≥ 0 | same-named snake_case columns |
| `orderLines[].discountPercent` | `number`, 0 ≤ d < 100, default 0 | `order_lines.discount_percent` |

- `POST`: omitted fields → `NULL` (lines → 0 discount).
- `PUT`: request-level quote fields are updated **only if present in the payload**
  (`model_fields_set`), so the existing detail-page edit form (which doesn't send them)
  never wipes them. Order lines are replaced as today; a line without `discountPercent` → 0.
- `totalCost` remains required and is the grand total.
- Activity log: unchanged behavior; the new fields are added to `_FIELD_LABELS` /
  `_changed_fields` so edits to them are logged (constitution VII).

## `RequestOut` (response, snake_case)

Adds: `quote_number, quote_date, quote_valid_until, currency, net_total, shipping_amount,
tax_amount, fees_amount` (all nullable) and `order_lines[].discount_percent` (number).

## `GET /organizations/me/settings`

```json
{"required_fields": [], "buyer_aliases": ["ACME Corp", "Lio Technologies, Inc.", "askLio"]}
```

## `PATCH /organizations/me/settings` (semantics changed: merge)

Admin only (unchanged). Body: any subset of settings keys. Only keys present are updated.

| Case | Status |
| --- | --- |
| `{"buyer_aliases": ["ACME Corp"]}` | 200; `required_fields` unchanged |
| `{"required_fields": ["vat_id"]}` | 200; `buyer_aliases` unchanged |
| > 20 aliases, empty alias, alias > 120 chars, unknown key | 422 |
| Non-admin | 403 |

Response: the full, merged settings object.
