# Feature Specification: Reliable Vendor-Quote Extraction

**Feature Branch**: `001-reliable-quote-extraction`

**Created**: 2026-10-22

**Status**: Draft

**Input**: User description: "When my team uploads our vendor quotes, the extracted data is often wrong — fields come out incorrect or empty, and sometimes the upload errors out completely. I've attached the five quotes we've been trying it with so you can see for yourself." — Acme Corp admin (Case study, Task 1)

---

## Context *(informational)*

On the **New Request** page a requester uploads a vendor-offer PDF. The system reads it and pre-fills the procurement request form: title, vendor, vendor tax ID, department, order lines, total cost and commodity group. The requester reviews, corrects and submits; the request then goes to a buyer or admin for approval.

The customer reports three kinds of failure on five real quotes (`quotes/` at the repository root, ground truth in **Appendix A**):

| Symptom | What the requester sees |
| --- | --- |
| **Hard failure** | A red error banner and an empty form, sometimes with raw technical error text. |
| **Wrong values** | The form fills in, but with the wrong vendor (often the buyer's own company), tax ID, total or line items (alternatives added, heading rows as lines, discounts lost). |
| **Empty values** | Fields stay blank with a "Could not extract" warning even though the data is in the PDF — or a warning that reads like an error for data the quote genuinely doesn't contain. |

This specification defines what "reliable extraction" means for the requester, so the behaviour can be planned, built and regression-tested against the five reference quotes.

## Clarifications

### Session 2026-10-22

- Q: Which amount becomes the request's total cost (and is later compared against the approval threshold)? → A: The **grand total** (net total + shipping + tax + fees).
- Q: How are excluded alternatives presented to the requester? → A: A **read-only informational notice**; no one-click add-back.
- Q: What is Department pre-filled with, now that it is no longer taken from the quote? → A: The **requester's own profile department**; empty if the profile has none.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Uploading a quote never fails outright (Priority: P1)

As a **requester**, when I upload a vendor quote, I want the form to be pre-filled with whatever could be extracted — never an empty form with a technical error — so that I can always continue my request.

**Why this priority**: A hard failure blocks the whole flow and destroys trust; it is the first complaint in the customer's report. Partial data with clear warnings is always more useful than nothing.

**Independent Test**: Upload each of the five reference quotes three times; every upload ends with a pre-filled form; no message contains technical error text.

**Acceptance Scenarios**:

1. **Given** a quote with no vendor tax ID (verdeform, Hartwell), **When** it is uploaded, **Then** the form is pre-filled and the tax ID is simply empty — the upload does not fail.
2. **Given** a quote containing heading rows with no quantity or price, **When** it is uploaded, **Then** extraction succeeds; a single unusable value never discards the rest of the extracted data.
3. **Given** amounts printed with currency symbols and thousands separators ("$1,409.06"), **When** the quote is uploaded, **Then** they are read as numbers.
4. **Given** the extraction service is slow or temporarily unavailable, **When** the requester uploads a quote, **Then** the system retries automatically within a bounded time, and if it still fails shows a plain-language message ("The service is busy, please try again in a minute") — never internal error text.
5. **Given** a PDF whose file type the browser reports as empty or generic, or whose extension is upper-case (`.Pdf`), **When** the requester selects it, **Then** it is accepted as a PDF; a file that is not actually a PDF is rejected with "Please upload a PDF file".
6. **Given** a fresh installation, **When** an operator sets the system up following the README, **Then** the required configuration (including the extraction service credentials) is documented in a template, so extraction is not broken by missing configuration.

---

### User Story 2 - The vendor and its tax ID are identified correctly (Priority: P1)

As a **requester**, I want the vendor to be the company that *issued* the quote and the tax ID to be that vendor's own tax ID, so that the request — and later supplier matching — refers to the right company.

**Why this priority**: The buyer's own company ("Lio Technologies, Inc.", "ACME Corp") is often the most prominent name on the quote and was taken as the vendor; the tax ID was confused with permit, registration, routing and account numbers. A wrong vendor is worse than an empty one because it may go unnoticed.

**Independent Test**: Upload the five reference quotes; compare vendor and tax ID with Appendix A.

**Acceptance Scenarios**:

1. **Given** the Apple quote, where "Lio Technologies, Inc." appears under "Prepared for" and the vendor only as "Apple Business Team" / email domain, **When** it is uploaded, **Then** the vendor is Apple and the tax ID is 94-2404110.
2. **Given** any quote addressed to the buyer's organization or one of its configured alternative names, **When** it is uploaded, **Then** the vendor is never the buyer; if the issuer cannot be determined, the vendor field is left empty and flagged rather than filled with the buyer.
3. **Given** the Greenmantle quote, which prints LLC No., Seller's Permit, ABA routing and account numbers next to "EIN: 85-3252405", **When** it is uploaded, **Then** the tax ID is 85-3252405.
4. **Given** the Hollis quote, which prints "Permit No.: 333 571207" and "EIN: 94 1985704", **When** it is uploaded, **Then** the tax ID is 94-1985704 (normalised format).
5. **Given** a quote with no vendor tax ID (verdeform, Hartwell), **When** it is uploaded, **Then** the tax ID is empty — no other number is substituted.
6. **Given** an organization administrator, **When** they maintain the list of alternative names their organization appears under on quotes, **Then** subsequent extractions for that organization use that list, other organizations are unaffected, and changing one organization setting does not reset the others.

---

### User Story 3 - Order lines contain only what is actually being bought (Priority: P1)

As a **requester**, I want the pre-filled order lines to contain only the positions included in the quoted total, so that I don't request items the vendor offered only as alternatives and don't have to delete empty lines.

**Why this priority**: Alternatives inflate the request amount (Hollis: +$3,920 on a $1,880 offer) and distort what the approver sees; heading rows create empty $0 lines on two of five quotes.

**Independent Test**: Upload the five reference quotes; the order lines match Appendix A exactly.

**Acceptance Scenarios**:

1. **Given** the Hollis quote, where items 1.1a and 1.1b follow "Alternative to the preceding item" and show "U.P." instead of a total, **When** it is uploaded, **Then** the lines are exactly 1.1 ($1,560.00) and 1.2 ($320.00).
2. **Given** the Greenmantle quote, where item 4 reads "Alternative: vertical logo" and item 5 is marked "(Alt.)", **When** it is uploaded, **Then** items 4 and 5 are not lines; items 2 and 3 are.
3. **Given** heading rows with no quantity and no price (Greenmantle item 1, Hollis "1. Moss art panel"), **When** the quote is uploaded, **Then** they are not lines.
4. **Given** the verdeform quote's upsell text ("Have you met our Moss Duo? … just MSRP $79"), **When** it is uploaded, **Then** no line is created for it.
5. **Given** positions were excluded as alternatives, **When** the form is shown, **Then** the requester sees an informational notice naming them (e.g. "2 alternative items were not added: 1.1a, 1.1b"), distinct from errors and not blocking submission. The notice is read-only; a requester who wants an alternative adds it as a line manually.

---

### User Story 4 - Amounts, discounts and totals are correct (Priority: P2)

As a **requester** (and as a **buyer** approving the request), I want line prices, discounts and the request total to match the quote, so that the amount I submit — and the approval decision based on it — is right.

**Why this priority**: Wrong totals change what approvers see and, once an approval threshold exists, approval outcomes (Hollis is $1,880 net but $2,042.15 gross around a $2,000 threshold). Most totals are already read correctly once P1 stories are met; the total-cost definition (FR-022) must be settled first.

**Independent Test**: Upload the five reference quotes; compare each line total, net total, shipping, tax and grand total with Appendix A; edit a line and verify the discount and total behave as specified.

**Acceptance Scenarios**:

1. **Given** Greenmantle item 2 (unit price 894.08, discount −20 %, line total 715.26), **When** it is uploaded, **Then** the line keeps unit price 894.08, discount 20 % and line total 715.26.
2. **Given** a discounted line, **When** the requester changes its quantity, **Then** the recalculated line total still applies the discount (it is not reset to unit price × quantity).
3. **Given** any reference quote, **When** it is uploaded, **Then** the system captures the net total, shipping, tax and grand total separately, with the values in Appendix A, plus the currency.
4. **Given** a quote, **When** it is uploaded, **Then** the request's total cost is set to the quote's grand total (e.g. Hollis → $2,042.15, Greenmantle → $1,686.14).
5. **Given** the requester edits order lines, **When** the total cost is recalculated, **Then** it remains a grand total: the sum of the edited lines plus the captured shipping, tax and fees (it does not silently switch to a net total).

---

### User Story 5 - Totals are cross-checked and mismatches are flagged (Priority: P2)

As a **requester**, I want the system to check that the extracted lines add up to the quote's total and warn me precisely when they don't, so that an extraction mistake is caught before I submit.

**Why this priority**: A safety net for anything P1–P4 miss; turns silent errors into visible, specific warnings.

**Independent Test**: For the five reference quotes no mismatch warning appears; for a quote with a deliberately altered line, a specific warning appears on the affected line/total.

**Acceptance Scenarios**:

1. **Given** a line where quantity × unit price × (1 − discount) differs from its line total by more than $0.02, **When** the form is shown, **Then** that line is highlighted with a warning stating the expected and extracted amounts.
2. **Given** the sum of lines (plus shipping where applicable) differs from the extracted net total by more than $0.02, **When** the form is shown, **Then** the total is highlighted with a warning stating both amounts.
3. **Given** all checks pass, **When** the form is shown, **Then** no reconciliation warning appears.
4. **Given** a reconciliation warning, **When** the requester reviews it, **Then** submission is still possible (warning, not a blocker).

---

### User Story 6 - Missing data is reported honestly (Priority: P2)

As a **requester**, I want to be told the difference between "this quote doesn't contain it" and "the system couldn't read it", so that I'm not alarmed by expected gaps and don't overlook real ones.

**Why this priority**: Two of five quotes legitimately have no tax ID, yet today the requester gets a warning that reads like an error; a legitimate total of 0 is also reported as missing.

**Independent Test**: Upload verdeform and Hartwell; the tax ID gap is reported as "not in the document" (informational). Force an unreadable field; it is reported as "could not extract".

**Acceptance Scenarios**:

1. **Given** a quote without a vendor tax ID, **When** it is uploaded, **Then** the requester sees an informational note ("No tax ID found in the quote") rather than an error-style warning.
2. **Given** a field that is present in the document but could not be extracted (e.g. vendor cleared because it matched the buyer), **When** the form is shown, **Then** the requester sees a "please fill in" warning for that field.
3. **Given** an extracted amount that is legitimately 0, **When** the form is shown, **Then** it is not reported as missing.

---

### User Story 7 - Department is not filled with the customer's name (Priority: P3)

As a **requester**, I want the Department field not to be filled with the vendor's view of the customer (company name, contact person, "Attn: Purchasing / Engineering"), so that I don't submit a wrong department.

**Why this priority**: Wrong on all five quotes today, but easy for the requester to correct and with low business impact.

**Independent Test**: Upload the five reference quotes; Department is never a company name, contact person or "Attn" line from the quote.

**Acceptance Scenarios**:

1. **Given** any reference quote, **When** it is uploaded, **Then** Department is not taken from the quote; it is pre-filled with the requester's own profile department, or left empty if their profile has none.

---

### User Story 8 - Quote reference data is captured (Priority: P3)

As a **buyer**, I want the quote number, quote date and validity date captured with the request, so that I can reference the offer with the vendor, spot duplicates and see whether the offer has expired.

**Why this priority**: Useful for audit and follow-up; not part of the customer's complaint.

**Independent Test**: Upload the five reference quotes; compare with Appendix B.

**Acceptance Scenarios**:

1. **Given** any reference quote, **When** it is uploaded, **Then** quote number, quote date and (where printed) valid-until date match Appendix B; a missing valid-until date is left empty.

---

### User Story 9 - Extraction quality is measurable and diagnosable (Priority: P3)

As a **support engineer / developer**, I want every extraction to be repeatable against the reference quotes and diagnosable after the fact, so that regressions are caught before release and customer reports can be investigated.

**Why this priority**: Enables safe iteration on all other stories; invisible to the requester.

**Independent Test**: Run the reference evaluation; it reports per-field accuracy and hard-failure rate for the five quotes over N runs. Inspect a past extraction's output, timing and model version.

**Acceptance Scenarios**:

1. **Given** the reference quotes and Appendix A, **When** the evaluation runs N times per quote, **Then** it reports per-field accuracy (vendor, tax ID, lines, net total, grand total) and the hard-failure rate.
2. **Given** the input-tolerance and reconciliation rules, **When** the automated test suite runs, **Then** they are verified without calling the external extraction service.
3. **Given** a customer reports a bad extraction, **When** support investigates, **Then** the extracted output, processing time and model version of that extraction are available — without the full quote text being written to logs.

---

### Edge Cases

- **Upper-case extension / odd file type** (`QuoteA0492_23.Pdf`; browser reports empty type) → accepted if it is really a PDF.
- **Slightly damaged PDF** (Hollis has a broken cross-reference table) → still processed.
- **Labels separated from values** in the PDF's internal order (Apple totals block, Hollis EIN) → still paired correctly.
- **Vendor name only in a logo image** (verdeform, partly Apple) → vendor recovered from email domain, website, body text or terms & conditions; if impossible, left empty and flagged — never the buyer.
- **Brand vs. legal entity** (verdeform vs. "Bloomcraft Interiors, Inc." in the T&C footer) → legal entity preferred when printed (see Assumptions).
- **Several 9-digit numbers** (EIN, permit, routing) → only the one labelled as the vendor's tax ID is used; when two different labelled tax IDs exist, none is guessed.
- **Alternative marked only by price notation** ("U.P.", unit price without total) or introduced on the previous line / after a page break → excluded.
- **Heading row with the same text as the next priced row** (Greenmantle 1 and 2) → only the priced row is kept, not duplicated.
- **Shipping/installation printed as an item in the table** (Hollis 1.2, Hartwell 2) → kept as a line; **shipping/fees only in the totals block** (Greenmantle $215, Apple eWaste fee $4) → captured as document-level amounts, not lines.
- **Decimal quantities and unusual units** (13.78 sq ft, 15.75 lin ft, "lump sum") → kept as printed; missing quantity defaults to 1.
- **Configuration bullets / long descriptions** under one item → part of that item's description.
- **Page subtotals, "Carried forward" rows, T&C, product notes** → never lines.
- **Every row is an alternative** → the requester is told no billable lines were identified rather than given an empty list silently.
- **Free-of-charge position** with a printed $0.00 total → kept (printed zero ≠ no price).
- **Total far above any approval threshold** (Hartwell $17,000 net) → extracted normally; approval rules apply downstream.
- **Requester without an organization** → cannot extract (unchanged permission model).

## Requirements *(mandatory)*

### Functional Requirements

**Robustness (US1)**

- **FR-001**: The system MUST return a pre-filled form whenever any data could be extracted; a single missing, null or malformed value MUST NOT discard the rest.
- **FR-002**: The system MUST read amounts written with currency symbols, thousands separators or currency words as numbers, and MUST default a missing quantity to 1.
- **FR-003**: The system MUST obtain the extraction result in a guaranteed machine-readable shape, and MUST handle the cases "service declined" and "response cut off" with a clear message.
- **FR-004**: The system MUST bound the time spent on the extraction service and retry transient failures automatically before giving up.
- **FR-005**: The system MUST NOT show internal or technical error text to the requester; every failure MUST map to a plain-language, actionable message.
- **FR-006**: The system MUST accept a file as a PDF if its reported type is a PDF type **or** its name ends in `.pdf` (any case), and MUST reject files whose content is not a PDF — consistently at upload, at parsing and when the PDF is attached to the submitted request.
- **FR-007**: The installation MUST ship a configuration template listing every required setting, including the extraction service credentials.

**Vendor and tax ID (US2)**

- **FR-008**: The system MUST identify the vendor as the issuer of the quote, never the recipient, and MUST prefer the issuer's legal entity name when one is printed.
- **FR-009**: The system MUST know the buyer's organization name and its configured alternative names, and MUST never return any of them as the vendor; if the result matches the buyer, the vendor MUST be left empty and flagged.
- **FR-010**: Organization administrators (and only they) MUST be able to maintain their organization's alternative names; the list applies only to their organization, and updating one organization setting MUST NOT reset another.
- **FR-011**: The system MUST return as tax ID only the vendor's US Employer Identification Number, in the format XX-XXXXXXX, and MUST NOT return permit, registration, routing, account, customer, quote or phone numbers, or the buyer's tax ID.
- **FR-012**: The system MUST preserve the association between printed labels and their values regardless of the PDF's internal text order.

**Order lines (US3)**

- **FR-013**: The system MUST include as order lines only positions that are part of the quoted total.
- **FR-014**: The system MUST exclude alternatives/options identified by wording ("Alternative", "Alt.", "Option", "optional", "instead of item …") or by price notation indicating the amount is not in the total ("U.P.", unit price without line total).
- **FR-015**: The system MUST exclude heading/grouping rows with neither quantity nor price, and MUST NOT create lines from text outside the item table (upsells, T&C, notes, page subtotals, carried-forward rows).
- **FR-016**: The system MUST keep positions with a quantity and a printed price, including a printed zero, and MUST keep shipping/installation printed as items in the table.
- **FR-017**: The system MUST record each excluded position with its reason (`alternative` | `heading` | `promotional`) and MUST show the requester an informational, non-blocking notice listing excluded alternatives.
- **FR-018**: Excluded alternatives MUST be presented to the requester as a read-only informational notice only; the system MUST NOT offer a one-click action to add them back.

**Amounts (US4)**

- **FR-019**: The system MUST capture per line: description, quantity, unit, unit price, discount (percent, may be zero) and line total net of discount.
- **FR-020**: The system MUST capture per quote: net total, shipping, tax, grand total and currency, each independently (any may be absent).
- **FR-021**: Editing a line's quantity or unit price MUST recalculate its total including its discount.
- **FR-022**: The request's total cost MUST be the **grand total** (net total + shipping + tax + fees) — at extraction it is the quote's printed grand total; after the requester edits lines it MUST be recalculated as Σ line totals + captured shipping + tax + fees. Any approval threshold MUST compare against this amount.

**Reconciliation (US5)**

- **FR-023**: The system MUST check each line (quantity × unit price × (1 − discount) ≈ line total) and the document (Σ lines [+ shipping where applicable] ≈ net total) within ±$0.02.
- **FR-024**: On a mismatch the system MUST show a specific, non-blocking warning on the affected line or total, naming expected and extracted amounts.

**Missing data (US6)**

- **FR-025**: The system MUST distinguish "not present in the document" (informational) from "present but not extracted" (warning) in what it reports to the requester.
- **FR-026**: A legitimately zero amount MUST NOT be reported as missing.

**Department (US7)**

- **FR-027**: The system MUST NOT fill Department with the customer company, contact person or "Attn" line from the quote; instead Department MUST be pre-filled with the requester's own profile department, and left empty if the profile has none.

**Quote metadata (US8)**

- **FR-028**: The system MUST capture quote number, quote date and valid-until date when printed.

**Quality and diagnosis (US9)**

- **FR-029**: The reference quotes and their expected values (Appendices A and B) MUST be evaluable automatically, reporting per-field accuracy and hard-failure rate over repeated runs.
- **FR-030**: Input-tolerance, tax ID, buyer-guard and reconciliation rules MUST be covered by automated tests that do not call the external extraction service.
- **FR-031**: For each extraction the system MUST make the output, processing time and model version available to support, without writing the full quote content to logs.
- **FR-032**: Extraction results MUST be as repeatable as the service allows (the same quote should give the same result run to run).

### Key Entities *(include if feature involves data)*

- **Quote (vendor offer)**: an uploaded PDF from a vendor to the buyer; has a header (issuer, recipient, quote number, dates), an item table, a totals block and surrounding text (notes, T&C).
- **Buyer Organization**: the tenant using the system; has a name and a list of alternative names it appears under on quotes (e.g. "ACME Corp", "Lio Technologies, Inc.", "askLio").
- **Vendor**: the issuer of the quote; name (legal entity preferred) and US tax ID (EIN) if printed.
- **Order Line**: a billable position — description, quantity, unit, unit price, discount %, line total (net of discount).
- **Excluded Position**: a quote row deliberately not turned into an order line — item number, short description, printed amount, reason (`alternative` | `heading` | `promotional`).
- **Quote Totals**: net total, shipping, tax, grand total, currency.
- **Extraction Result**: everything pre-filled for the requester — the above plus commodity group, excluded positions, reconciliation findings, and per-field status (`extracted` | `not in document` | `could not extract`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: **0 hard failures** across 3 uploads of each of the 5 reference quotes (15 uploads).
- **SC-002**: Vendor name and tax ID (or correctly empty) are correct for **5/5** reference quotes in 3/3 runs (Appendix A).
- **SC-003**: Order lines match Appendix A (same count; each line total within ±$0.02) for **5/5** quotes in 3/3 runs; 0 alternative, heading or promotional rows appear as lines.
- **SC-004**: Net total and grand total match Appendix A within ±$0.02 for 5/5 quotes in 3/3 runs.
- **SC-005**: For every reference quote either the lines reconcile with the net total, or the requester sees a specific mismatch warning — never a silent mismatch.
- **SC-006**: **No** message shown to the requester contains internal/technical error text, across all reference uploads and simulated service failures (timeout, rate limit, outage, malformed response).
- **SC-007**: For verdeform and Hartwell, the missing tax ID is reported as informational, not as an error.
- **SC-008**: A requester can go from upload to a submittable form for each reference quote without deleting any pre-filled line and without correcting vendor or tax ID.
- **SC-009**: Automated tests for input tolerance (null values, "1,234.56" strings), tax ID rules, buyer guard and reconciliation pass without network access to the extraction service.
- **SC-010**: Median time from upload to pre-filled form does not exceed today's median by more than ~10 % on the reference quotes.

## Assumptions

- **Documents**: text-based US vendor quotes in English, amounts in USD, like the five reference quotes. Scanned/image-only PDFs and non-US tax IDs are out of scope; a non-EIN tax ID is left empty.
- **Vendor naming**: when both a brand and the issuer's legal entity are printed (verdeform / Bloomcraft Interiors, Inc.), the legal entity is preferred. Either is acceptable for SC-002 for verdeform; the buyer never is.
- **Shipping**: shipping printed only in the totals block is captured as a separate document-level amount, not an order line. Shipping printed as an item inside the table is a line.
- **Buyer alternative names**: the demo organization (Acme Corp) is pre-configured with "ACME Corp", "Lio Technologies, Inc." and "askLio", because the reference quotes are addressed to those names. Other organizations start with an empty list and their behaviour is otherwise unchanged.
- **Commodity group**: classification continues to work as today; improving it (e.g. shortlisting, customer booking rules) is out of scope.
- **Approval**: today every request requires buyer/admin approval; this feature does not change the approval flow.
- **Users and permissions**: unchanged; extraction is available to members of an organization (a user with no organization cannot extract).
- **Total cost**: the request total is the grand total (clarified 2026-10-22). Reconciliation (FR-023) still checks lines against the **net** total, since tax and totals-block shipping are not lines. When a quote prints no grand total, net + shipping + tax + fees is used.
- **Data shape compatibility**: existing requests and the request form continue to work; new fields (discount, totals breakdown, quote metadata, excluded positions, field statuses) are additive.

### Dependencies

- The external extraction (language-model) service and its credentials.
- The five reference quotes in `quotes/` and the ground truth in Appendices A and B.
- Organization settings (for buyer alternative names) and the future approval-threshold rule (consumer of the total-cost definition).

### Out of Scope

- Recovering vendor names that exist only inside images (vision/OCR) — candidate follow-up if SC-002 is not met for verdeform from text alone.
- Splitting commodity classification from extraction, model comparison, background processing, removing the double upload.
- Suggesting catalog articles at negotiated prices (Task 2), customer-specific commodity booking rules (Task 3) and the approval threshold (Bonus).

---

## Appendix A — Reference quotes: expected values *(ground truth)*

| Quote file | Vendor | Tax ID | Expected order lines (→ line total) | Must NOT be lines | Net total | Shipping | Tax (+ fees) | Grand total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `QT-4120-Cust-14918.pdf` | Greenmantle Moss Studio, LLC | 85-3252405 | 2 · Moss Art Panel, Mixed Moss 63 x 31.5 in, 1 ea. × 894.08, −20 % → **715.26**<br>3 · Logo integration "asklio" horizontal, 1 ea. × 622.00 → **622.00** | 1 (heading), 4 "Alternative: vertical logo" (heading), 5 "(Alt.)" 430.00 | **1,337.26** | 215.00 (totals block) | 115.34 + 18.54 = 133.88 | **1,686.14** |
| `QT-OF2312380-Cust-57692.pdf` | Bloomcraft Interiors, Inc. (brand: verdeform) | — (none) | 1 · verdeform CUSTOM module, 13.78 sq ft × 52.00 → **716.56**<br>2 · verdeform CUSTOM edge greening, 15.75 lin ft × 7.65 → **120.49**<br>3 · Logo acrylic white "askLio", 1 ea. × 350.00 → **350.00** | "Moss Duo … MSRP $79" upsell | **1,187.05** | 113.85 (totals block) | 102.38 + 9.82 = 112.20 | **1,413.10** |
| `QuoteA0492_23.Pdf` | Hollis Greenscapes | 94-1985704 | 1.1 · Moss panel "70:30" with "askLio" lettering, 1 × 1,560.00 → **1,560.00**<br>1.2 · Transport, packing and shipping, 1 × 320.00 → **320.00** | "1. Moss art panel" (heading), 1.1a alt. "U.P." 2,090.00, 1.1b alt. "U.P." 1,830.00 | **1,880.00** | (in line 1.2) | 162.15 | **2,042.15** |
| `Quote_1__Lio_Technologies_Inc__1x_MBA___2214703918.pdf` | Apple (Apple Inc. / Apple Business Team) | 94-2404110 | 13" MacBook Air: Apple M2 Chip – Space Gray, 1 × 1,409.06 → **1,409.06** | Configuration bullets (part of description) | **1,409.06** | — | 121.53 + eWaste fee 4.00 | **1,534.59** |
| `Quote_Hartwell_Cleveland_ACME_Grinding_Machine.pdf` | Hartwell Industrial Tools, Inc. | — (none) | 1 · Grinding machine HW-GS 450, 1 ea. × 15,000.00 → **15,000.00**<br>2 · Delivery and installation, 1 lump sum × 2,000.00 → **2,000.00** | — | **17,000.00** | (in line 2) | 1,402.50 | **18,402.50** |

**Buyer names on these quotes (never the vendor):** Lio Technologies, Inc. (Greenmantle, verdeform, Hollis, Apple), ACME Corp (Hartwell). **Department:** never "Lukas Heinzmann", "Vladimir Keil", "Mr. Vladimir Keil", "Lio Technologies, Inc." or "Purchasing / Engineering".

## Appendix B — Reference quotes: quote metadata

| Quote file | Quote number | Quote date | Valid until |
| --- | --- | --- | --- |
| `QT-4120-Cust-14918.pdf` | 4120 | 11/28/2023 | 01/27/2024 |
| `QT-OF2312380-Cust-57692.pdf` | OF2312380 | 11/26/2023 | 12/10/2023 |
| `QuoteA0492_23.Pdf` | A0492/23 | 12/12/2023 | — (not printed) |
| `Quote_1__Lio_Technologies_Inc__1x_MBA___2214703918.pdf` | 2214703918 - 18000012048816 | 02/20/2024 | 03/20/2024 |
| `Quote_Hartwell_Cleveland_ACME_Grinding_Machine.pdf` | Q-HW-2026-041 | 05/08/2026 | 06/07/2026 |
