# Quickstart: validating catalog article suggestions

Contracts: [catalog-api.md](./contracts/catalog-api.md),
[requests-catalog-links.md](./contracts/requests-catalog-links.md). Ground truth: spec
Appendix A (also `backend/tests/fixtures/catalog_reference.json`).

## 1. Start

```bash
cd lio-procurement-app
docker compose up --build -d     # migrates 0008, seeds, embeds the catalog (needs OPENAI_API_KEY)
docker compose logs backend | grep -i "embedded"   # e.g. "Catalog embedded: +393 descriptions"
```

Without a key the app works; suggestions use exact-token matching only.

## 2. Offline checks (merge gate)

```bash
cd backend && python -m pytest -q
cd frontend && npx tsc --noEmit && npm run build
```

Covers ranking, unit comparability, savings (R1 −102.11, R2 −395.26, R3 −1,240.00,
R5 +240.94, R9 −275.00), MOQ note, contracted supplier (R11 +25.00 above agreement), lexical
fallback, server-side snapshot + foreign-article 422, buyer totals, usage report and tenant
isolation — with stubbed embeddings and verifier.

## 3. Live evaluation (SC-001 – SC-004, SC-006)

```bash
cd backend && python scripts/eval_suggestions.py --runs 3
```

Expected: every expected article in the top 3, every ★ first, 0 must-not articles, R4/R6/R7
empty, savings ±$0.01; per-line latency printed (median ≤ 1 s target; first uncached lookups
may exceed it — record the numbers in the PR).

## 4. UI walkthrough

As `requester@acme.com`:

| Step | Expect |
| --- | --- |
| Upload `QT-OF2312380-Cust-57692.pdf` | Line 1 shows HAR-00172, Harborview Facility LLC, $44.59 / sq ft, "Save $102.11"; line 3 (acrylic logo) shows nothing |
| Apply HAR-00172 | Description/price/unit replaced, qty 13.78 kept, total $614.45; "From Harborview Facility LLC, not Bloomcraft Interiors, Inc." + **Switch vendor**; **Undo** restores |
| Upload the Apple quote | Same 13" laptop from 3 suppliers, cheapest first: DEL-00905 "$28.94 more expensive", …, AUR-00413 "$240.94 more expensive" — never a saving |
| Upload the Hartwell quote | No suggestions on either line |
| Add a line "Toner cartridge cyan", qty 5, $150 | MON-00922 $95 first, then BEA-01877, DEL-00890; "Save $275.00"; "below minimum order quantity (10)" |
| Dismiss a suggestion | It doesn't come back until the description changes |
| Submit verdeform without applying | As `buyer@acme.com`, the request shows line 1 "Catalog alternative: HAR-00172 — potential saving $102.11" and the total |

As `admin@acme.com`: Articles page → **Agreement usage** shows linked share, realised and
missed savings for the period. As `admin@walmart.com`: no suggestions anywhere (empty catalog).
