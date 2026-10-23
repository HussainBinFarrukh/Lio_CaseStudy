# Feature Specification: Suggest Catalog Articles with Negotiated Prices

**Feature Branch**: `002-catalog-article-suggestions`

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description: "People raise requests and go off buying whatever they find. We've negotiated specific prices for specific articles with our suppliers. When someone creates a request, I want the system to suggest the matching articles we already have on catalog, so we actually use those agreements." — Acme Corp admin (Case study, Task 2, `FDE-Case-Study.pdf`)

---

## Context *(informational)*

Each organization keeps its own **master data**: a supplier list and an **article catalog** in which every article is tied to one supplier and carries a **negotiated price** (article number, description, unit price, unit, currency, and a quantity). Acme Corp's catalog holds **1,920 articles from 120 suppliers**, all in USD.

Today the catalog is disconnected from purchasing:

| Observation | Consequence |
| --- | --- |
| The catalog can only be browsed on its own page (substring search on description / article number). | A requester has to know the catalog exists and search it manually; nobody does. |
| On **New Request** — whether lines come from an uploaded quote or are typed in — nothing refers to the catalog. | Requesters buy from whichever vendor sent a quote, at that vendor's price, even when a negotiated agreement exists. |
| Order lines store free text and a price only; they have no link to a catalog article. | Nobody can tell afterwards whether a request used an agreement, or how much was left on the table. |
| **381 descriptions are offered by more than one supplier** at different prices (e.g. "Toner cartridge cyan" from 6 suppliers, $95–$177). | A useful suggestion must rank alternatives, not just find "a" match. |
| **None of the five vendors in the Task 1 reference quotes is in Acme's supplier list.** | Most valuable suggestions will point to a *different, contracted* supplier — which affects how a request's vendor is handled. |

The five Task 1 reference quotes (`quotes/` at the repository root) plus a few typed-in lines form the reference scenarios for this feature (**Appendix A**). They include true matches (moss walls, laptops, toner), traps that look similar but are not the same article ("Desk organizer acrylic" vs. an acrylic logo; "CNC machining" vs. a grinding machine), and a line with no catalog equivalent at all.

## Clarifications

### Session 2026-10-23

- Q: When an applied article's supplier differs from the request's vendor? → A: **Warn and offer a one-click vendor switch**; requests never mix suppliers (FR-016).
- Q: Must a requester give a reason for not using a cheaper catalog alternative? → A: **No**; the buyer sees the flag (FR-023).
- Q: What does an article's "quantity" mean? → A: **Minimum order quantity**; price is per unit; lines below it get a note; quantities are never converted (FR-024).

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Matching catalog articles are suggested while I build a request (Priority: P1)

As a **requester**, while I create a request — from an uploaded quote or by typing lines myself — I want each order line to show the catalog articles that match it, with supplier, negotiated price and the difference to my current price, so that I can see an existing agreement before I commit to buying elsewhere.

**Why this priority**: This is exactly what the customer asked for; without it the negotiated agreements are invisible at the moment of decision.

**Independent Test**: Upload the verdeform quote; line 1 (custom moss, 13.78 sq ft × $52.00) shows catalog article HAR-00172 (Harborview Facility LLC, custom moss wall, $44.59 per sq ft) with a saving of about $102. Type a line "toner cartridge cyan"; the six catalog offers appear, cheapest first.

**Acceptance Scenarios**:

1. **Given** an order line pre-filled from an uploaded quote, **When** the form is shown, **Then** up to a small number of matching catalog articles (default 3) are suggested for that line, each with article number, description, supplier, negotiated unit price, unit, and the price difference versus the line's current unit price.
2. **Given** a requester typing or editing a line description, **When** they pause typing, **Then** suggestions update for the new description without reloading the page.
3. **Given** several catalog articles with the same or equivalent description from different suppliers (e.g. toner cyan from 6 suppliers), **When** suggestions are shown, **Then** they are ordered by relevance first and, among equally relevant articles, by lowest negotiated price per unit.
4. **Given** a catalog article that is cheaper than the line's current price, **When** it is suggested, **Then** the expected saving for the line's quantity is shown (e.g. "Save $102.11").
5. **Given** a catalog article that is more expensive than the quote (Apple MacBook Air at $1,409.06 vs. catalog laptops at $1,520–$1,650), **When** it is suggested, **Then** it is shown honestly as more expensive, never presented as a saving.
6. **Given** a line with no matching article (Hartwell grinding machine), **When** the form is shown, **Then** no suggestions appear for that line and nothing implies an agreement exists.
7. **Given** a line with no description yet, **When** the form is shown, **Then** no suggestions are requested for it.

---

### User Story 2 — I can apply a suggestion in one action (Priority: P1)

As a **requester**, I want to accept a suggested article with one click, so that the line takes the catalog description, negotiated price and unit, and the request records that it uses an agreement.

**Why this priority**: Suggestions only change behaviour if acting on them is easier than ignoring them; recording the link is what makes agreement usage measurable.

**Independent Test**: Apply HAR-00172 to verdeform line 1; the line shows the catalog description, $44.59, unit sq ft, keeps quantity 13.78, total becomes $614.45, and the line is marked as a catalog article. Undo restores the original line.

**Acceptance Scenarios**:

1. **Given** a suggestion on a line, **When** the requester applies it, **Then** the line's description, unit price and unit are replaced with the catalog values, the article and its supplier are linked to the line, the quantity is kept, and the line total and request total are recalculated.
2. **Given** an applied suggestion, **When** the requester undoes it, **Then** the line returns to its previous values and the link is removed.
3. **Given** a line linked to a catalog article, **When** the requester edits its unit price away from the negotiated price, **Then** the line shows that it deviates from the agreement (and by how much), and the deviation is kept with the request.
4. **Given** a line linked to a catalog article whose unit differs from the original line's unit, **When** it is applied, **Then** the requester is warned to check the quantity (e.g. "quote line is in sq ft, article is per piece"). The quantity is kept as entered; an article quantity above the line quantity adds a "below minimum order quantity" note (FR-024).
5. **Given** a submitted request, **When** it is opened later, **Then** catalog-linked lines still show their article number, supplier and negotiated price at the time of submission, even if the catalog changed since.
6. **Given** an applied article from a supplier other than the request's current vendor, **When** it is applied, **Then** the requester sees "This article is from <supplier>, not <vendor>" with a one-click action to switch the request's vendor (name and tax ID) to that supplier; requests never mix suppliers (FR-016).

---

### User Story 3 — Quotes from contracted suppliers are checked against the agreement (Priority: P2)

As a **requester** (and the organization), when a quote comes from a supplier we already have in master data, I want its lines compared with that supplier's negotiated articles, so that a quote above the agreed price is caught.

**Why this priority**: The strongest form of "use our agreements": the supplier is the same, so a higher price is simply an overcharge. Lower priority than P1 only because none of the five reference quotes comes from a contracted supplier.

**Independent Test**: Use a test quote from a supplier in master data (e.g. "Montclair Supply Corp.") listing "Toner cartridge cyan" at $120; the line is flagged as $25 above the negotiated $95 and the agreement article is the top suggestion.

**Acceptance Scenarios**:

1. **Given** an extracted vendor whose name or tax ID matches a supplier in the organization's master data, **When** the form is shown, **Then** the vendor is recognised as a contracted supplier and this is visible to the requester.
2. **Given** a recognised supplier, **When** suggestions are computed, **Then** that supplier's own matching articles are ranked first.
3. **Given** a line priced above the same supplier's negotiated price for the matching article, **When** the form is shown, **Then** the line is flagged with the negotiated price and the difference.
4. **Given** a vendor name that differs only in punctuation or legal suffix from the master-data name ("Montclair Supply Corp" vs. "Montclair Supply Corp."), **When** matching, **Then** it is recognised.
5. **Given** a vendor not in master data (all five reference quotes), **When** the form is shown, **Then** no "contracted supplier" indication is shown and cross-supplier suggestions (US1) still work.

---

### User Story 4 — Buyers see agreement usage when approving (Priority: P2)

As a **buyer**, when I review a request for approval, I want to see which lines use catalog agreements, which lines had a cheaper catalog alternative that was not used, and the total potential saving, so that I can push back before approving.

**Why this priority**: Gives the organization leverage where suggestions were ignored; turns the customer's complaint ("people buy whatever they find") into something a buyer can act on.

**Independent Test**: Submit the verdeform quote without applying HAR-00172; the buyer's view shows line 1 as "catalog alternative available — potential saving $102.11".

**Acceptance Scenarios**:

1. **Given** a request with catalog-linked lines, **When** a buyer views it, **Then** those lines are marked as using an agreement, with article number and supplier.
2. **Given** a request where a cheaper matching catalog article existed but was not applied, **When** a buyer views it, **Then** the line shows the alternative and the potential saving, and the request shows the total potential saving.
3. **Given** a request where no catalog alternative existed, **When** a buyer views it, **Then** nothing is flagged.
4. **Given** a requester who ignored a cheaper alternative, **When** submitting, **Then** submission is not blocked and no reason is asked for; the buyer sees the missed-saving flag (FR-019, FR-023).

---

### User Story 5 — Suggestions are relevant, not noisy (Priority: P2)

As a **requester**, I want suggestions only when an article is genuinely the same kind of item, so that I trust them and don't learn to ignore them.

**Why this priority**: A catalog of 1,920 articles contains many superficially similar words; irrelevant suggestions would quickly train users to ignore the feature.

**Independent Test**: For the reference lines in Appendix A, no article from the "must not be suggested" column appears.

**Acceptance Scenarios**:

1. **Given** the verdeform line "Logo acrylic white 3/16 in 'askLio'", **When** suggestions are computed, **Then** "Desk organizer acrylic" and "Floor mat logo mat" are not suggested.
2. **Given** the Hartwell line "Grinding machine HW-GS 450", **When** suggestions are computed, **Then** "CNC machining …" services are not suggested.
3. **Given** a requester dismisses a suggestion on a line, **When** the line is unchanged, **Then** the dismissed article is not shown again for that line.
4. **Given** the matching cannot decide between relevant and irrelevant, **When** in doubt, **Then** it shows fewer suggestions rather than more.

---

### User Story 6 — Agreement usage is measurable (Priority: P3)

As an **admin**, I want to see how often requests use catalog agreements and how much potential saving was missed, so that I can tell whether the agreements are being used and where to negotiate next.

**Why this priority**: Confirms the feature solves the customer's problem over time; not needed for the first release.

**Independent Test**: After creating several requests, the admin sees the share of order lines linked to catalog articles, the total realised savings and the total missed savings for a period.

**Acceptance Scenarios**:

1. **Given** requests in the organization, **When** the admin opens the overview, **Then** they see, for a chosen period, the number and share of catalog-linked lines, realised savings versus original quote prices, and missed savings.
2. **Given** another organization's requests, **When** the admin views the overview, **Then** they are never included.

---

### Edge Cases

- **Organization with an empty catalog** (Walmart, Schaeffler, Siemens, BMW today) → no suggestions, no errors, no empty "suggestions" panels.
- **Same description, several suppliers, different prices** → all relevant offers ranked by price; ties broken by the supplier already on the request.
- **Different units** (quote in sq ft, article per piece; quote "lump sum", article per hour) → price comparison shown only when units are comparable; otherwise the suggestion is shown without a saving figure and with a unit warning.
- **Article "quantity" other than 1** (e.g. toner cyan at Delmar: $139, quantity 10) → the price is per unit, so the saving is computed normally, plus a "below minimum order quantity (10)" note when the line quantity is lower (FR-024).
- **Line with quantity 0 or no price** (not yet filled in) → suggestions shown, saving not computed.
- **Very long or very short descriptions** (configuration bullet lists; "Toner") → matching still returns sensible results or none.
- **Catalog price changes after a request is submitted** → the request keeps the negotiated price that applied when the article was linked.
- **Article deleted from the catalog after being linked** → the request still shows the stored article number, description, supplier and price.
- **Discounted quote line** (Greenmantle −20 %) → the comparison uses the net unit price after discount.
- **Currency** → all catalog articles are USD; a line in another currency gets no saving figure.
- **Multiple lines matching the same article** → each line gets its own suggestion; applying one does not change the others.
- **Heading / alternative rows** (see Task 1) → they are not order lines, so they get no suggestions.

---

## Requirements *(mandatory)*

### Functional Requirements

**Suggestions (US1, US5)**
- **FR-001**: The system MUST suggest matching catalog articles for each order line while a request is being created or edited, for lines from an uploaded quote and for typed lines alike.
- **FR-002**: Suggestions MUST come only from the requesting user's own organization's catalog.
- **FR-003**: Each suggestion MUST show article number, description, supplier, negotiated unit price, unit, currency, and — when comparable — the unit-price difference and the saving or extra cost for the line's quantity.
- **FR-004**: Suggestions MUST be ranked by relevance, then by lowest comparable negotiated price, then preferring the supplier already on the request.
- **FR-005**: The system MUST show at most a small, configurable number of suggestions per line (default 3).
- **FR-006**: The system MUST match on meaning, not only on literal substrings, so that differently worded descriptions of the same item match ("custom moss module per sq ft" ↔ "Custom moss wall, preserved reindeer moss, made to measure").
- **FR-007**: The system MUST NOT suggest articles that merely share words with the line but are a different kind of item (Appendix A, "must not be suggested"), and MUST prefer no suggestion over an irrelevant one.
- **FR-008**: Suggestions MUST update when a line's description changes, without reloading the page, and MUST NOT noticeably slow down typing or the form.
- **FR-009**: A requester MUST be able to dismiss a suggestion for a line.
- **FR-010**: A more expensive catalog article MUST be shown as more expensive, never as a saving.

**Applying a suggestion (US2)**
- **FR-011**: The requester MUST be able to apply a suggestion in one action, replacing the line's description, unit price and unit with the catalog values and keeping the quantity (subject to FR-024).
- **FR-012**: An applied suggestion MUST be reversible until the request is submitted.
- **FR-013**: A catalog-linked order line MUST store the article reference plus a snapshot of article number, description, supplier and negotiated unit price at the time of linking.
- **FR-014**: When a catalog-linked line's unit price is edited away from the negotiated price, the system MUST mark and store the deviation.
- **FR-015**: Line totals and the request total MUST be recalculated after applying or undoing a suggestion.
- **FR-016**: When an applied article's supplier differs from the request's vendor, the system MUST warn the requester and offer a one-click switch of the request's vendor (name and tax ID) to the article's supplier. A request MUST NOT mix suppliers: applying an article from another supplier never changes the vendor silently, and lines linked to a different supplier than the request's vendor MUST be flagged until resolved.

**Contracted suppliers (US3)**
- **FR-017**: The system MUST recognise a request's vendor as a contracted supplier when its tax ID, or its name ignoring case, punctuation and legal suffixes, matches a supplier in the organization's master data.
- **FR-018**: For a recognised supplier, the system MUST rank that supplier's matching articles first and MUST flag lines priced above the supplier's negotiated price for the matching article, showing the difference.

**Approval view (US4)**
- **FR-019**: The request view used for approval MUST show, per line, whether it is catalog-linked, and, for unlinked lines, any cheaper matching catalog article and the potential saving.
- **FR-020**: The request view MUST show the total potential saving across unlinked lines.
- **FR-021**: Potential savings MUST be computed with the same matching and ranking rules as the requester's suggestions, so the buyer and requester see consistent information.

**Reporting (US6)**
- **FR-022**: Admins MUST be able to see, per period, the share of catalog-linked order lines, realised savings and missed savings for their organization only.

**Policy**
- **FR-023**: The requester MUST NOT be asked for a reason when a cheaper catalog alternative is not used, and submission MUST NOT be blocked; the buyer sees the missed-saving flag (FR-019).
- **FR-024**: A catalog article's "quantity" is its **minimum order quantity**; its unit price is per single unit. Price comparisons and savings use the per-unit price directly. A line linked to (or suggested with) an article whose minimum order quantity exceeds the line quantity MUST show a non-blocking "below minimum order quantity (N)" note. Applying a suggestion never converts the line quantity.

**Quality**
- **FR-025**: The reference scenarios (Appendix A) MUST be evaluable automatically: for each reference line, which articles are suggested, in which order, and whether any "must not be suggested" article appears.
- **FR-026**: Matching, ranking and saving calculations MUST be covered by automated tests that do not depend on an external AI service being reachable.
- **FR-027**: If any external service used for matching is unavailable, request creation MUST still work; suggestions are simply absent, with no error shown in their place.

### Key Entities

- **Supplier**: a company in the organization's master data — name, tax ID, category, country, contact.
- **Catalog Article (agreement)**: an article the organization has a negotiated price for — article number, supplier, description, unit price, unit, currency, quantity (meaning per FR-024).
- **Order Line**: a position of a procurement request — description, quantity, unit, unit price, line total; optionally **linked** to a catalog article.
- **Article Link (snapshot)**: on a linked order line — article reference, article number, description, supplier, negotiated unit price at linking time, and any price deviation.
- **Suggestion**: for one order line — a candidate catalog article with relevance rank, comparable unit-price difference and saving/extra cost for the line's quantity.
- **Savings Summary**: per request and per period — realised savings (linked lines vs. original price), missed savings (cheaper alternatives not used).

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every reference line in Appendix A with an "expected suggestion", that article appears among the top 3 suggestions; for 100 % of lines with a listed "best" article, it is ranked first.
- **SC-002**: **0** articles from the "must not be suggested" column appear for their reference lines.
- **SC-003**: For reference lines with no catalog equivalent, **no** suggestion is shown.
- **SC-004**: Saving / extra-cost figures for Appendix A lines are correct to ±$0.01.
- **SC-005**: A requester can apply a suggestion in **one** action and undo it in one action; applied lines are stored with the article link and negotiated-price snapshot.
- **SC-006**: Suggestions appear within **1 second** of a line being shown or edited (95th percentile on the reference catalog of 1,920 articles), and request creation is never blocked by suggestion lookup.
- **SC-007**: Users in other organizations never see Acme's articles or suppliers in suggestions (verified for all seeded tenants).
- **SC-008**: A buyer viewing a request where a cheaper catalog article was not applied sees the alternative and the potential saving (verified on the verdeform reference: $102.11).
- **SC-009**: After rollout, the share of order lines linked to catalog articles is measurable per period (baseline today: 0 %, because lines cannot be linked).

---

## Assumptions

- **Catalog = negotiated prices**: every catalog article's unit price is the price negotiated with that supplier; there are no separate price lists, tiers or validity periods.
- **Currency**: all catalog prices are USD; comparisons with non-USD lines are not made.
- **Supplier per request**: a request has one vendor (current data model); cross-supplier articles are handled by the vendor switch in FR-016.
- **Article quantity**: a minimum order quantity with a per-unit price (FR-024, clarified).
- **Matching basis**: matching uses the line's description (and unit, where present); the article number is used when a quote quotes it verbatim.
- **Quote vendors**: none of the five Task 1 vendors is in Acme's supplier list; suggestions for those quotes are therefore cross-supplier.
- **Catalog maintenance**: admins maintain the catalog as today (seeded data); editing the catalog in the UI is out of scope.
- **Line quality**: suggestions rely on Task 1 delivering correct order lines (no alternatives or heading rows as lines).
- **Permissions**: any organization member creating or editing a request sees suggestions; buyers and admins see the approval view; admins see reporting.

## Dependencies

- Organization master data: suppliers and articles (already seeded and organization-scoped).
- Task 1 (`specs/001-reliable-quote-extraction/`): correct vendor name, tax ID and order lines from uploaded quotes.
- Approval flow and request detail view (US4).
- The bonus approval-threshold feature, if built, consumes the request total — which may change when a suggestion is applied.

## Out of Scope

- Creating or editing catalog articles and suppliers in the UI; importing price lists.
- Automatically replacing lines with catalog articles without the requester's action.
- Placing orders with suppliers or sending purchase orders.
- Supplier enrichment (descriptions, websites) and supplier onboarding.
- Commodity-group / booking rules (Task 3) and the approval threshold (bonus task).
- Price negotiation workflows, volume tiers and contract validity dates.

---

## Appendix A — Reference scenarios *(ground truth)*

Lines from the Task 1 reference quotes (`quotes/` at the repository root) and typed-in lines, matched against Acme Corp's seeded catalog.

| # | Order line (source) | Line price | Expected suggestion(s) (★ = should rank first) | Must NOT be suggested | Expected comparison |
| --- | --- | --- | --- | --- | --- |
| R1 | verdeform CUSTOM moss module, forest & ball moss, 13.78 sq ft (verdeform quote, line 1) | $52.00 / sq ft | ★ **HAR-00172** Custom moss wall, preserved reindeer moss, made to measure — Harborview Facility LLC — $44.59 / sq ft | Floor mat logo mat (any supplier) | Save $7.41 / sq ft → **$102.11** for 13.78 sq ft |
| R2 | Moss Art Panel, Mixed Moss 63 x 31.5 in, MDF frame (Greenmantle quote, line 2) | $715.26 / ea. (894.08 −20 %) | **RED-00196** Framed preserved moss panel with company logo cut-out — Redwood Facility Group — $320.00 / piece; **HAR-00172** (per sq ft) | Floor mat logo mat | RED-00196: save $395.26 per piece (compared with the net, discounted price); HAR-00172: units differ (piece vs. sq ft), no saving figure |
| R3 | Moss panel "70:30" with "askLio" lettering, 63 x 31.5 in (Hollis quote, line 1.1) | $1,560.00 / ea. | ★ **RED-00196** Framed preserved moss panel with company logo cut-out — $320.00 / piece; **HAR-00172** (per sq ft) | Floor mat logo mat; Modular living green plant wall (living plants, not moss) | RED-00196: save $1,240.00 |
| R4 | Logo acrylic white 3/16 in "askLio", with standoffs (verdeform quote, line 3) | $350.00 / ea. | — (no equivalent) | **Desk organizer acrylic** (LAK-00861); **Floor mat logo mat** | No suggestion |
| R5 | 13" MacBook Air: Apple M2, 16 GB, 512 GB (Apple quote) | $1,409.06 / piece | ★ **DEL-00905** Business laptop 13" ultralight / 16 GB / 1 TB — Delmar Systems Inc. — $1,438.00; then GRA-01344 $1,452.00; **AUR-00413** Aurora Solutions Corp. $1,650.00 (same article, 4 offers) | — | DEL-00905 shown as **$28.94 more expensive**, AUR-00413 as **$240.94 more expensive**; never as a saving |
| R6 | Grinding machine HW-GS 450 (Hartwell quote, line 1) | $15,000.00 / ea. | — (no equivalent) | **CNC machining** 3-axis / 5-axis / turning (SIE-00117, NOR-00087, NOR-00092); Stretch film machine grade | No suggestion |
| R7 | Delivery and installation, lump sum (Hartwell quote, line 2) | $2,000.00 / lump sum | — (no equivalent for machine installation) | Last-mile delivery (parcel services) | No suggestion |
| R8 | Typed: "Toner cartridge cyan", qty 5 | (none) | ★ **MON-00922** Montclair Supply Corp. $95.00; then **BEA-01877** Beacon Supply LP $117.00; **DEL-00890** Delmar Supply Inc. $139.00 (top 3 of 6 offers) | Toner cartridge magenta / yellow / black | Prices shown; no saving (no current price). Prices are per unit regardless of the article quantity (FR-024) |
| R9 | Typed: "Toner cartridge cyan", qty 5, unit price $150.00 | $150.00 / piece | ★ **MON-00922** $95.00 | other colours | Save $55.00 / piece → **$275.00**. Per FR-024, also a "below minimum order quantity (10)" note, since MON-00922 has quantity 10 |
| R10 | Typed: "Business laptop 14 inch i7 32GB" | (none) | ★ **LUM-00440** Business laptop 14" i7 / 32 GB / 1 TB SSD — Lumen Solutions Co. — $1,130.00; then PIN-01868 $1,262.00, VER-00379 $1,297.00 (same article, 8 offers; HUD-00015 $1,520.00 ranks 4th) | Docking stations; keyboard/mouse sets | — |
| R11 | Quote from **Montclair Supply Corp.** (contracted supplier, synthetic test quote): "Toner cartridge cyan" at $120.00 | $120.00 / piece | ★ **MON-00922** (same supplier) $95.00 — flagged as above the negotiated price | other suppliers' toner ranked after MON-00922 | **$25.00 above agreement** per piece (US3) |


**Ground-truth correction (2026-10-23):** R5 and R10 originally named AUR-00413 and HUD-00015 as the top suggestion, but the seeded catalog offers the *identical* article from several suppliers at lower prices. FR-004 (relevance, then lowest price) therefore ranks DEL-00905 and LUM-00440 first; the rows above follow FR-004.

**Full offer list for "Toner cartridge cyan"** (for ranking checks): MON-00922 Montclair Supply Corp. $95.00 (qty 10) · BEA-01877 Beacon Supply LP $117.00 (qty 5) · DEL-00890 Delmar Supply Inc. $139.00 (qty 10) · CED-01816 Cedar Supply Corp. $149.00 (qty 1) · PIN-01856 Pinnacle Supply Co. $160.00 (qty 10) · LAK-00863 Lakeview Supply LP $177.00 (qty 5).

**Tenant isolation check:** signed in as `admin@walmart.com` (empty catalog), R1–R10 return **no** suggestions.
