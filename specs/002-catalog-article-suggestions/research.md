# Phase 0 Research: Suggest Catalog Articles with Negotiated Prices

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-10-23

Evidence: the seeded catalog (`backend/app/data/articles.py`) and two live experiments with the
OpenAI API on the Appendix A reference lines (scripts kept out of the repo; results below).

## Baseline

| Observed | Consequence |
| --- | --- |
| `GET /articles` is org-scoped substring search (`ilike`) on description / article number, 25 per page; only the Articles page uses it. | Nothing links requests to the catalog (spec context). |
| `order_lines` has no article reference. | Agreement usage is unmeasurable (US2, US6). |
| 1,920 articles but only **393 unique descriptions**; 381 descriptions offered by several suppliers; units: piece 870, month 244, pack 226, hour 159, … `sq ft` 1. | Matching can work per unique description; ranking must handle identical descriptions at different prices. |
| Suppliers have `name` and `vat_id` (all `10-00xxxxx`). | Contracted-supplier recognition (US3) can reuse Task 1's `normalize_company` + EIN normalisation. |
| Task 1 extraction already returns clean order lines, net-of-discount totals, vendor and tax ID. | Suggestions can be computed directly from the pre-filled form (no new extraction work). |

## R1 — Matching approach (FR-006, FR-007, SC-001 – SC-003)

**Decision**: two stages.

1. **Retrieve** with embeddings: `text-embedding-3-small` at **256 dimensions**, one vector per
   catalog article (computed once, stored), cosine similarity against the line description,
   top **6 unique descriptions**.
2. **Verify** with an LLM relevance check (`gpt-4o-mini`, Structured Outputs, `temperature=0`):
   "is each candidate the *same kind of item* as the line?" — returns one boolean per candidate.
   Only confirmed candidates become suggestions.

**Evidence** (experiment 1 — embeddings only, small@256):

| Line | Correct article: score (rank) | Best trap: score |
| --- | --- | --- |
| R1 moss module | Custom moss wall **0.47 (1st)** | Floor mat 0.34 |
| R2 Moss Art Panel | Framed moss panel 0.64 (1st), Custom moss wall 0.58 (2nd) | Floor mat 0.37 |
| R3 Moss panel 70:30 | Framed moss panel 0.64 (1st) | Living plant wall 0.41 |
| R4 Logo acrylic | — | **Desk organizer acrylic 0.59 (1st)** |
| R5 MacBook Air | Business laptop 13″ **0.42 (1st)** | — |
| R6 Grinding machine | — | **CNC machining 0.51 (1st)** |
| R7 Delivery & installation | — | Last-mile delivery 0.50 |
| R8 Toner cyan | exact 1.00 | Toner yellow 0.78 |
| R10 Laptop 14″ i7 | 0.93 (1st) | Docking station 0.42 |

Ranking is right whenever a match exists, but **no threshold separates matches from traps**
(a correct 0.42 vs a trap 0.59). 512 dimensions and `text-embedding-3-large` (experiment 2a)
shift scores but keep the overlap (large: R1 correct 0.62 < living plant wall 0.69).

Experiment 2b — small@256 top-6 + `gpt-4o-mini` relevance check: **all traps rejected**
(R4, R6, R7 return nothing; toner colours dropped), R1/R2/R5/R8/R10 correct; R3 kept the ★
article but dropped the secondary HAR-00172. Latency of the check: **median 0.60 s, max 1.7 s**
per line; embedding a line ~30 ms; scanning 393 vectors in pure Python ~6 ms.

**Alternatives considered**: embeddings + threshold/rules (cannot meet SC-002/SC-003 — chosen
first, rejected on evidence, user re-decided 2026-10-23); keyword/BM25 only (fails R5
MacBook↔laptop); larger embedding model (no separation gain); LLM only over the whole catalog
(too slow/expensive per keystroke).

**Prompt notes**: the verifier is told that the same product type and purpose counts even if
brand/specs differ (laptop model vs generic business laptop), and that sharing a material, word
or industry does not (acrylic logo ≠ desk organizer; grinding machine ≠ machining service;
installing a machine ≠ parcel delivery; cyan ≠ yellow toner). Line and candidate units are
included as context.

## R2 — Latency, caching, failure (FR-008, FR-027, SC-006)

- **Cache** verdicts in-process (LRU, ~5,000 entries) keyed by
  `(organization_id, normalised line description, article description)`; embeddings of line
  texts cached the same way. Re-renders, re-orders and submit-time recomputation hit the cache.
- **Batching**: uploaded-quote lines are sent in **one** request (one embedding call for all
  lines, one LLM call per line run concurrently with a small thread pool).
- **Typing**: the frontend debounces description edits (500 ms) and shows "Checking the
  catalog…" while a lookup runs; results never block the form.
- **Bounded**: OpenAI client with `timeout=8 s`, `max_retries=1` for suggestions (separate from
  extraction's settings). On any failure or missing key → **lexical fallback** (R7); the
  response never contains an error for the UI to show (FR-027).
- **Honest expectation**: median well under 1 s, but uncached first lookups can exceed 1 s
  (observed max 1.7 s); SC-006 is verified with the eval script's timing output.

## R3 — Storing embeddings (constitution VIII portability)

- **Decision**: per-article columns `embedding` (`LargeBinary`, 256 × float32 = 1 KB) and
  `embedding_model` (`String`). Pure-Python cosine over the org's **unique descriptions**,
  held in an in-memory index per organization, rebuilt when the set of embedded article ids
  changes.
- **Population**: `python -m app.embed_catalog` runs after `app.seed` at container start
  (idempotent: only articles with no vector for the current model; non-fatal without a key),
  plus lazy fill of missing vectors on the first lookup. Acme's 1,920 articles = 393 unique
  texts ≈ 1 s and well under one cent.
- **Alternatives**: pgvector (Postgres-only, breaks SQLite tests and adds an extension — XI);
  numpy (new dependency, unnecessary at this size).

## R4 — Ranking and comparison (FR-003, FR-004, FR-010, US3)

- **Order**: confirmed candidates grouped by description; groups ordered by similarity
  (relevance); within a group by **lowest unit price**; ties → article from the request's
  current vendor / recognised contracted supplier first. A recognised contracted supplier's
  confirmed articles are moved to the top (US3). Return at most `limit` (default 3) articles.
- **Comparable price**: line unit price **net of discount** (`totalPrice / amount`, so
  Greenmantle compares 715.26, not 894.08). Units normalised (`pieces|piece|pcs|ea|ea.|each`
  → `piece`, `sq ft|sqft|square feet` → `sq ft`, `hours|hr` → `hour`, …). Saving shown only
  when units are comparable, currency is USD and the line has a price and quantity > 0.
- **Figures**: `unit_difference = article_price − line_price`;
  `line_effect = unit_difference × quantity` → negative = **saving**, positive = **more
  expensive** (never shown as a saving — FR-010). Rounded to cents (SC-004: R1 −102.11,
  R2 −395.26, R3 −1,240.00, R5 +240.94, R9 −275.00).
- **Minimum order quantity** (FR-024): `article.quantity > line quantity` → note
  "below minimum order quantity (N)".

## R5 — Contracted supplier recognition (FR-017, FR-018)

- Match the request's vendor against the org's suppliers by normalised EIN (Task 1
  `normalize_ein`) or normalised name (Task 1 `normalize_company`: case, punctuation, legal
  suffixes). Returned with suggestions as `contractedSupplier {id, name}`.
- Overcharge: if a confirmed article from that same supplier has a lower comparable price than
  the line → `agreementCheck {articleNumber, negotiatedPrice, difference}` on the line.
- None of the five reference quotes' vendors is in master data → verified with a synthetic
  Montclair Supply Corp. line (R11).

## R6 — Persisting links and alternatives (FR-013, FR-014, FR-019 – FR-022)

- **Linked line**: `catalog_article_id` (FK, `SET NULL` on delete) + snapshot
  (`article_number`, `article_description`, `article_supplier_name`, `negotiated_unit_price`,
  `article_min_quantity`) + `original_unit_price` (the line's price before applying, for
  realised savings). The **server** fills the snapshot from the org's catalog when it receives
  `catalogArticleId` — never from client values; foreign-org ids → 422 (constitution I).
  Deviation (FR-014) = `unit_price − negotiated_unit_price`, derived from stored columns.
- **Unlinked line**: on create/update the server runs the same suggestion service (FR-021) and
  stores the best **cheaper** confirmed alternative: `alternative_article_number`,
  `alternative_supplier_name`, `alternative_unit_price`, `potential_saving`. The buyer view and
  reporting read stored values (consistent, no LLM calls on view).
- **Activity log**: creation summary gains "N of M lines use catalog agreements"; edits that
  change links are covered by the order-lines change detection (constitution VII).

## R7 — Fallback without the AI service (FR-027, FR-026)

Lexical matching: normalise text (casefold, strip punctuation), match when the article's
description tokens are all contained in the line's tokens (or vice versa for short typed lines
of ≥ 2 tokens). Yields "Toner cartridge cyan" → the six cyan offers, never "Desk organizer
acrylic" for a logo. Used when no key, on timeout/error, and in offline tests.

## R8 — Vendor switch (FR-016, clarified)

Frontend-only action: when an applied article's supplier ≠ request vendor (normalised compare),
the line shows "From <supplier>, not <vendor>" with **Switch vendor** (sets vendor name + tax ID
from the supplier). The server rejects nothing, but marks lines whose linked supplier differs
from the vendor (`supplierMismatch`) so the buyer sees it.

## R9 — Evaluation & tests (FR-025, FR-026)

- Offline pytest: ranking, units, savings (SC-004 figures), MOQ note, contracted-supplier
  matching, fallback, snapshot/tenant validation via the API, buyer-view and reporting
  aggregates — with **stub embedder and stub verifier** (no network).
- Live `scripts/eval_suggestions.py`: runs R1–R11 against the seeded catalog through the real
  pipeline, checks expected / ★ / must-not / savings, and prints per-line latency (SC-006).
  Ground truth in `tests/fixtures/catalog_reference.json`.

All Technical Context unknowns resolved.
