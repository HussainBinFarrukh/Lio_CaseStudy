# Contract: PDF parse & extraction

Conventions follow constitution IV: extraction payloads are camelCase; errors from
`/pdf/parse` are `HTTPException` with a string `detail`; extraction failures are returned in
the envelope with HTTP 200.

## `POST /pdf/parse` (changed)

Auth: Bearer (any authenticated user — unchanged).
Body: `multipart/form-data`, field `file`.

| Case | Status | Body |
| --- | --- | --- |
| Declared type `application/pdf`/`application/x-pdf` **or** name ends `.pdf` (any case), content starts with `%PDF-` | 200 | `{"text": "<layout text>"}` |
| Not a PDF (type/name and magic bytes check fails) | 400 | `{"detail": "Please upload a PDF file"}` |
| > 10 MB | 413 | `{"detail": "PDF exceeds the 10MB limit"}` |
| Unparseable PDF | 422 | `{"detail": "We couldn't read this PDF. Please fill in the form manually."}` |
| Valid PDF without extractable text (e.g. a scan) | 200 | `{"text": ""}` — the UI shows "no readable text, please fill in manually" |

`text` is now layout-mode text with ` | ` column separators (research R1). Consumers treat it
as opaque.

## `POST /extraction` (changed)

Auth: Bearer **and organization membership** (`get_current_membership`; 403
"User is not part of any organization" otherwise). *Breaking for users without an
organization — intentional (spec edge case; research R5).*

Request: `{"text": string}` (unchanged).

Response 200 — success:

```json
{
  "success": true,
  "extractionId": "6f1c…",
  "data": {
    "title": "Moss Art Panel and Logo",
    "vendorName": "Hollis Greenscapes",
    "vatId": "94-1985704",
    "department": "Engineering",
    "quoteNumber": "A0492/23",
    "quoteDate": "2023-12-12",
    "validUntil": null,
    "currency": "USD",
    "orderLines": [
      {"positionDescription": "Moss panel \"70:30\" with \"askLio\" lettering …",
       "unitPrice": 1560.0, "amount": 1, "unit": "pieces",
       "discountPercent": 0, "totalPrice": 1560.0},
      {"positionDescription": "Transport, packing and shipping …",
       "unitPrice": 320.0, "amount": 1, "unit": "pieces",
       "discountPercent": 0, "totalPrice": 320.0}
    ],
    "totals": {"netTotal": 1880.0, "shipping": null, "tax": 162.15, "fees": null,
               "grandTotal": 2042.15},
    "totalCost": 2042.15,
    "commodityGroupId": 15,
    "commodityGroupName": "Office Equipment",
    "excludedPositions": [
      {"itemNo": "1", "description": "Moss art panel", "amount": null, "reason": "heading"},
      {"itemNo": "1.1a", "description": "As previous item, but ball moss only.",
       "amount": 2090.0, "reason": "alternative"},
      {"itemNo": "1.1b", "description": "As item 1.1, but forest moss throughout; …",
       "amount": 1830.0, "reason": "alternative"}
    ],
    "reconciliation": [],
    "fieldStatus": {
      "title": "extracted", "vendorName": "extracted", "vatId": "extracted",
      "department": "extracted", "orderLines": "extracted", "totalCost": "extracted",
      "commodityGroup": "extracted", "quoteNumber": "extracted", "quoteDate": "extracted",
      "validUntil": "not_in_document"
    }
  },
  "missingFields": null
}
```

- Existing keys (`title, vendorName, vatId, department, orderLines[].{positionDescription,
  unitPrice, amount, unit, totalPrice}, totalCost, commodityGroupId, commodityGroupName`,
  `missingFields`) keep name and type. `vatId`/`vendorName`/`department` remain strings
  (`""` when empty).
- New keys are additive: `extractionId`, `quoteNumber`, `quoteDate`, `validUntil`,
  `currency`, `orderLines[].discountPercent`, `totals`, `excludedPositions`,
  `reconciliation`, `fieldStatus`, `errorCode`.
- `missingFields`: human labels of fields with status `could_not_extract` only (or `null`).
- `totalCost`: grand total (FR-022).
- `reconciliation[]`: `{"scope": "line"|"net_total"|"grand_total", "lineIndex": int|null,
  "expected": number, "extracted": number}`.

Response 200 — failure (never technical text; research R4):

```json
{"success": false, "extractionId": "6f1c…", "errorCode": "service_busy",
 "error": "The extraction service is busy. Please try again in a minute."}
```

`errorCode ∈ {not_configured, service_busy, refused, too_long, unreadable}` (empty input text
→ `unreadable`). Mapping and messages: research R4.

## `PUT /requests/{id}/document` (changed)

Same acceptance rule as `/pdf/parse` (shared helper). Other behavior unchanged.

## Frontend client (`frontend/src/lib/api/index.ts`)

`ExtractedVendorData`, `ExtractionResponse`, `OrderLineInput` gain the optional fields above;
new types `QuoteTotals`, `ExcludedPosition`, `ReconciliationFinding`,
`FieldStatus = 'extracted' | 'not_in_document' | 'could_not_extract'`.
