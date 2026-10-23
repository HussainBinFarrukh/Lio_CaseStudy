# Contract: Catalog suggestions & usage

Conventions (constitution IV): inputs camelCase, responses camelCase for this new service
(like extraction), `HTTPException` with string `detail` for errors. All endpoints resolve the
organization via `get_current_membership`; data comes only from that organization (FR-002).

## `POST /catalog/suggestions`

Auth: any organization member. Never returns an error for matching problems (FR-027).

Request:

```json
{
  "vendorName": "verdeform",
  "vendorVatId": "",
  "limit": 3,
  "lines": [
    {"key": "0", "description": "verdeform CUSTOM - sq ft Module - forest & ball moss variant",
     "unit": "sq ft", "quantity": 13.78, "unitPrice": 52.0, "discountPercent": 0,
     "totalPrice": 716.56, "currency": "USD"}
  ]
}
```

- `lines`: 1–50; lines with an empty description are returned with no suggestions.
- `limit`: 1–5, default 3.

Response 200:

```json
{
  "source": "semantic",
  "contractedSupplier": null,
  "lines": [
    {
      "key": "0",
      "suggestions": [
        {"articleId": "…", "articleNumber": "HAR-00172",
         "description": "Custom moss wall, preserved reindeer moss, made to measure",
         "supplierId": "…", "supplierName": "Harborview Facility LLC",
         "unitPrice": 44.59, "unit": "sq ft", "currency": "USD", "minQuantity": 1,
         "relevance": 0.47, "comparable": true, "unitDifference": -7.41,
         "lineEffect": -102.11, "belowMinQuantity": false, "fromVendor": false}
      ],
      "agreementCheck": null
    }
  ]
}
```

| Case | Result |
| --- | --- |
| Organization has no catalog | `lines[].suggestions = []` |
| AI service unavailable / no key | `source: "lexical"`, exact-token matches only |
| Vendor matches a supplier (EIN or normalised name) | `contractedSupplier: {id, name}`; its confirmed articles first; `agreementCheck` when its price is lower than the line's |
| Not a member of an organization | 403 (as all org endpoints) |
| > 50 lines / invalid body | 422 |

## `GET /catalog/usage?from=YYYY-MM-DD&to=YYYY-MM-DD` (US6)

Auth: **admin** (`require_org_admin`). Both dates optional (default: last 30 days, inclusive).

```json
{"from": "2026-09-24", "to": "2026-10-23", "requestCount": 12, "lineCount": 30,
 "linkedLineCount": 9, "linkedShare": 0.3, "realisedSavings": 1420.55, "missedSavings": 310.0}
```

Non-admin → 403. Only the caller's organization is counted (SC-007).

## Frontend client (`frontend/src/lib/api/index.ts`)

New `catalog.suggest(input)` and `catalog.usage(from?, to?)` plus types `SuggestionLineInput`,
`ArticleSuggestion`, `LineSuggestions`, `SuggestionsResponse`, `CatalogUsage`.
