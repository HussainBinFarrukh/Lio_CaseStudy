# Feature Specification: Organization-Specific Commodity Booking Rules

**Feature Branch**: `003-org-booking-rules`

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description: "The commodity groups the system assigns don't match our accounting. For us, cable ties always have to be booked under Electrical Engineering, printer toner under IT Hardware, and small software subscriptions under Office Supplies — not where the system keeps putting them. They're quirks on our side, but they're non-negotiable." — Acme Corp admin (Case study, Task 3, `FDE-Case-Study.pdf`)

---

## Context *(informational)*

Every procurement request carries **one commodity group**, which drives how it is booked in accounting. When a quote is uploaded, the system proposes the group as part of extraction; the requester can change it in a drop-down before submitting. The taxonomy is a **single global list of 2,000 groups in 22 categories, shared by all organizations**; nothing about classification is organization-specific today.

What the taxonomy and the current behaviour look like for Acme's three items:

| Item | Groups that exist for it | What the system assigns today *(baseline, 2/2 runs)* | What Acme requires |
| --- | --- | --- | --- |
| Cable ties | No dedicated group. Plausible: "Fasteners Assortment" (151), "Fasteners Set" (327), "Electrical Installation" (352) | **15 · Office Equipment** | **11 · Facility Management / Electrical Engineering** |
| Printer toner | **204 · Office & Administration / Toner Cartridges** (+ 5 pack-size variants: 534, 864, 1194, 1524, 1854) | **15 · Office Equipment** | "IT Hardware" → **29 · Information Technology / Hardware** (closest existing group; see Assumptions) |
| Small software subscriptions | **31 · Software**, plus many license groups (Antivirus, Database, Backup, Office Productivity Suite …) | **31 · Software** | "Office Supplies" → no such group exists; stand-in **15 · Office Equipment** (FR-008, clarified) |

Observations that shape the requirements:

- The original classification instruction contained generic hard-coded hints ("Branded office decor/furniture → Office Equipment (15)", "Software/IT products → Software (31)"); the second directly contradicts Acme's rule, and the first appears to pull unrelated items (cable ties, toner) into group 15. **In this repository** Task 1 (`specs/001-reliable-quote-extraction/`) rewrote the extraction prompt without those hints; since then the model frequently returns **no** commodity group at all (observed on the Greenmantle and verdeform quotes, 2026-10-23), so the requester picks one manually. The "Today" baseline in Appendix A was measured on the pre-Task-1 code.
- Acme's rules are deliberately **against** the taxonomy's natural fit (toner has its own group; software has its own group). Better general classification cannot satisfy them — they must be applied as **explicit rules** that take precedence.
- The rules are **Acme's quirks only**. Walmart, Schaeffler, Siemens and BMW must keep today's behaviour.
- "Non-negotiable" means a request for one of these items must not end up booked elsewhere — neither by the system nor by a requester picking another group.

## Clarifications

### Session 2026-10-23

- Q: "Office Supplies" doesn't exist — what does Acme's subscription rule target? → A: the **existing group 15 · Office Equipment** (closest generic office bucket); no org-specific groups (FR-008).
- Q: What makes a subscription "small"? → A: recurring software subscription with an **annualised total below $2,000**, configurable per rule (FR-009).
- Q: Which group wins on mixed requests? → A: the **highest-value line**; advise splitting when two rules are involved (FR-011).

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Acme's booking rules are always applied (Priority: P1)

As an **Acme requester**, when my request is for cable ties, printer toner or a small software subscription, I want the commodity group set to Acme's mandated group automatically, so that accounting receives correctly booked requests without me knowing the rules.

**Why this priority**: This is the customer's explicit, non-negotiable requirement; today all three items are misbooked on every run.

**Independent Test**: As `requester@acme.com`, upload or type requests for the three items (Appendix A, R1–R3); each gets the mandated group, on every run.

**Acceptance Scenarios**:

1. **Given** an Acme request whose items are cable ties (e.g. "Cable ties nylon 8 in, black, pack of 100"), **When** the commodity group is determined, **Then** it is **Electrical Engineering (11)**.
2. **Given** an Acme request whose items are printer toner (e.g. "Toner cartridge black, high-yield, HP 59A"), **When** the commodity group is determined, **Then** it is **IT Hardware → Hardware (29)**, not "Toner Cartridges" (204) and not "Office Equipment" (15).
3. **Given** an Acme request for a small software subscription (e.g. "Project management tool subscription, monthly, 5 users × $12"), **When** the commodity group is determined, **Then** it is **15 · Office Equipment** (Acme's "Office Supplies", FR-008).
4. **Given** any of these requests, **When** they are created from an uploaded quote **or** entered manually **or** edited later, **Then** the same rule applies in all three paths.
5. **Given** the same request evaluated repeatedly, **When** the group is determined, **Then** the result is identical every time (rules are deterministic, not subject to model variance).

---

### User Story 2 — Rules are enforced and explained (Priority: P1)

As an **Acme requester**, I want to see why a group was chosen and be prevented from booking a rule-covered item elsewhere, so that the rule is transparent and actually holds.

**Why this priority**: "Non-negotiable" is only true if a requester cannot override it by picking another group in the drop-down; an unexplained, locked field would cause confusion and support tickets.

**Independent Test**: For a toner request, the group field shows "Hardware" with a note "Booking rule: printer toner → IT Hardware"; the requester cannot submit it with another group; a buyer or admin can.

**Acceptance Scenarios**:

1. **Given** a request where a booking rule applied, **When** the requester views the form, **Then** the commodity group shows the mandated group and a short explanation naming the rule (e.g. "Acme booking rule: printer toner is booked under IT Hardware").
2. **Given** a rule-covered request, **When** a requester tries to save it with a different group (via the form or directly via the system interface), **Then** the save is rejected with a message naming the rule.
3. **Given** a rule-covered request, **When** a **buyer or admin** changes the group, **Then** the change is allowed, a reason is required, and the override is recorded in the request's activity log.
4. **Given** a request where no rule applies, **When** the requester views it, **Then** the group is proposed as today and freely editable; no rule note is shown.

---

### User Story 3 — Rules are specific to the organization (Priority: P1)

As an **admin of another organization** (Walmart, Schaeffler, Siemens, BMW), I want Acme's quirks to have no effect on my organization, so that my requests keep being classified by the standard taxonomy.

**Why this priority**: The platform is multi-tenant; leaking one customer's accounting rules into another's bookings would be a correctness and trust failure.

**Independent Test**: As `admin@walmart.com`, create the same three requests; they are classified as without rules and no rule note appears.

**Acceptance Scenarios**:

1. **Given** a non-Acme organization, **When** a cable-tie, toner or software-subscription request is classified, **Then** no Acme rule is applied and no rule note is shown.
2. **Given** a non-Acme organization, **When** its users list commodity groups, **Then** the list is the unchanged global taxonomy (no organization-specific groups are created; FR-008).
3. **Given** two organizations with different rules for the same item, **When** each classifies that item, **Then** each gets its own mandated group.

---

### User Story 4 — Rules match the right items and only those (Priority: P2)

As an **Acme requester**, I want rules to apply only to the items they were written for, so that neighbouring items are not misbooked by an over-eager rule.

**Why this priority**: A rule on "cable" or "software" written naively would capture patch cables, EV charging cables, copy paper next to toner, or large enterprise software — swapping one misbooking for another.

**Independent Test**: Appendix A, R4–R10 keep their normal classification.

**Acceptance Scenarios**:

1. **Given** "Patch cable Cat 6, 3 ft" or "Charging cable J1772", **When** classified, **Then** the cable-tie rule does not apply.
2. **Given** "Copy paper letter size", "Printer, laser, A4" or "3D printer filament", **When** classified, **Then** the toner rule does not apply ("printer" alone is not toner).
3. **Given** a large software license (e.g. "ERP enterprise license, annual, 500 seats, $85,000") or a one-time perpetual license, **When** classified, **Then** the small-subscription rule does not apply.
4. **Given** item wording variations — "zip ties", "cable tie mounts", "nylon tie wraps"; "toner cartridge", "laser toner", "drum & toner kit"; "SaaS subscription", "monthly plan", "per-seat license, annual" — **When** classified, **Then** the corresponding rule applies.
5. **Given** a rule match is uncertain, **When** classified, **Then** the rule is not silently applied; the requester sees the normal proposal plus a hint ("This may fall under Acme's booking rule for …") and can confirm.

---

### User Story 5 — Requests with mixed items are booked predictably (Priority: P2)

As an **Acme requester**, when my request mixes a rule-covered item with other items (toner and copy paper), I want a predictable, explained group, so that I know how the request will be booked.

**Why this priority**: A request has only one commodity group; mixed requests are common for office purchases.

**Independent Test**: Request with toner $240 + copy paper $98 → group decided per FR-011, with an explanation.

**Acceptance Scenarios**:

1. **Given** a request with lines covered by a rule and lines not covered, **When** the group is determined, **Then** it follows FR-011 and the explanation states which line decided it.
2. **Given** a request with lines covered by two different rules (cable ties and toner), **When** the group is determined, **Then** it follows FR-011 and the requester is advised to split the request if the items must be booked separately.

---

### User Story 6 — Admins manage their organization's booking rules (Priority: P2)

As an **Acme admin**, I want to view, add, change and remove my organization's booking rules myself, so that new accounting quirks don't require a software change.

**Why this priority**: The customer called these "quirks" — more will come. Self-service avoids a support ticket per rule; but the three initial rules can be seeded, so this is not required for first value.

**Independent Test**: As `admin@acme.com`, add a rule "label printer tape → Office Equipment (15)"; a new request for label tape gets that group. As `buyer@acme.com`, editing rules is not possible.

**Acceptance Scenarios**:

1. **Given** an admin, **When** they open organization settings, **Then** they see the list of booking rules: what items each covers (description and example terms), any conditions (e.g. amount limit), and the target group.
2. **Given** an admin, **When** they add, edit or remove a rule, **Then** it takes effect for requests classified afterwards; existing requests are not changed automatically.
3. **Given** a rule targeting a group, **When** the admin saves it, **Then** the target must be a valid group available to the organization.
4. **Given** a buyer or requester, **When** they try to change booking rules, **Then** they cannot.
5. **Given** a rule change, **When** it is saved, **Then** who changed what and when is recorded.

---

### User Story 7 — Existing requests can be checked against the rules (Priority: P3)

As an **Acme admin**, I want to see which existing requests are booked differently from the current rules, so that I can correct historical bookings deliberately.

**Why this priority**: Useful for cleanup after rollout; not needed for correct new bookings.

**Acceptance Scenarios**:

1. **Given** existing requests, **When** the admin runs the check, **Then** they see requests whose group differs from what the current rules mandate, with the rule and the mandated group.
2. **Given** the check result, **When** the admin chooses to re-book selected requests, **Then** only those change, each with an activity-log entry; nothing changes automatically.

---

### Edge Cases

- **Item matches the rule but quote wording is unusual** ("Kabelbinder", "tie wraps", "TN-2420") → covered by the rule's example terms / meaning; if uncertain, hint instead of silent application (US4-5).
- **"Printer" vs. "toner"**: printers, printer paper, printer service contracts are not toner.
- **Toner vs. ink**: inkjet ink cartridges — [covered by the toner rule? Assumed **no** unless the admin adds it; see Assumptions].
- **"Small" boundary**: a subscription exactly at the threshold, monthly vs. annual billing, per-seat pricing → evaluated on the annualised total of the subscription lines (FR-009).
- **Software that is not a subscription** (perpetual license, one-time purchase, implementation services) → not covered by the subscription rule.
- **Hardware bundled with a subscription** (device + monthly plan) → mixed request (FR-011).
- **Requester picks the group before any lines exist** → the rule is evaluated once lines are known and the requester is informed if the group changes.
- **Request edited after submission** (lines changed to a rule-covered item) → rule re-evaluated on save.
- **Rule target group removed from the taxonomy** → the rule is flagged as invalid to admins and not applied; requests fall back to normal classification.
- **Two rules match the same line** → the more specific rule wins; if equally specific, the admin is warned when saving the second rule.
- **Organization without rules** → behaviour identical to today.
- **Classification service unavailable** → rules that can be decided from the lines alone still apply; otherwise the requester picks the group manually as today.

---

## Requirements *(mandatory)*

### Functional Requirements

**Rules and evaluation (US1, US4)**
- **FR-001**: The system MUST support organization-specific **booking rules**, each mapping a described kind of item (with optional conditions) to a target commodity group.
- **FR-002**: Acme Corp MUST have these rules: (a) cable ties → **Electrical Engineering (11)**; (b) printer toner → **IT Hardware**, i.e. **Hardware (29)**; (c) small software subscriptions → **15 · Office Equipment** (Acme's "Office Supplies", FR-008).
- **FR-003**: A matching booking rule MUST take precedence over the system's general classification.
- **FR-004**: Rule evaluation MUST be deterministic: the same request content always yields the same rule outcome.
- **FR-005**: Rules MUST be applied identically for requests created from an uploaded quote, entered manually, and edited later.
- **FR-006**: Rules MUST match the kind of item, not merely a shared word: the cable-tie rule MUST NOT apply to patch, network or charging cables; the toner rule MUST NOT apply to printers, paper or other printer supplies; the subscription rule MUST NOT apply to large or perpetual software licenses.
- **FR-007**: Rules MUST recognise common wording variants of their items (Appendix A, R1–R3 variants).
- **FR-008**: "Office Supplies" does not exist in the taxonomy; Acme's subscription rule MUST target the existing group **15 · Facility Management / Office Equipment** as its stand-in. No organization-specific commodity groups are created; the global taxonomy is unchanged.
- **FR-009**: A software subscription is "small" when it is recurring (monthly, annual or per-seat subscription; not perpetual) and the **annualised** total of the request's subscription lines is **below $2,000.00** (a monthly price × 12; $1,999.99 is small, $2,000.00 is not). The limit is a per-rule condition an admin can change.
- **FR-010**: When a rule match is uncertain, the system MUST NOT apply it silently; it MUST show the normal proposal plus a hint naming the possible rule, which the requester can accept.
- **FR-011**: When a request mixes rule-covered and other lines (or lines of different rules), the group of the **highest-value line** decides (rule group if that line is rule-covered, otherwise normal classification); the explanation names the deciding line; when two different rules are involved, the requester is advised to split the request.

**Enforcement and transparency (US2)**
- **FR-012**: When a rule determined the group, the form MUST show the mandated group and a short explanation naming the rule.
- **FR-013**: The system MUST reject saving a rule-covered request with a different group by a requester — in the user interface and in the system's programmatic interface alike — with a message naming the rule.
- **FR-014**: Buyers and admins MUST be able to override a rule-determined group with a mandatory reason; the override MUST be recorded in the request's activity log.
- **FR-015**: Which rule (if any) determined a request's group MUST be stored with the request.

**Tenant isolation (US3)**
- **FR-016**: Booking rules and any organization-specific commodity groups MUST apply to and be visible to their own organization only.
- **FR-017**: Organizations without rules MUST be classified exactly as today.

**Rule management (US6)**
- **FR-018**: Admins MUST be able to list, add, edit and remove their organization's booking rules; buyers and requesters MUST NOT.
- **FR-019**: A rule MUST consist of: a name, a description of the covered items, example terms (include / exclude), optional conditions (e.g. maximum annualised amount), and a target group that is valid for the organization.
- **FR-020**: Rule changes MUST apply to requests classified afterwards only, and MUST be recorded (who, what, when).
- **FR-021**: The initial Acme rules (FR-002) MUST be present without manual setup (seeded), and seeding MUST NOT overwrite rules an admin has since edited.

**Existing requests (US7)**
- **FR-022**: Admins MUST be able to list existing requests whose group differs from what the current rules mandate, and to re-book selected ones explicitly, each change logged.

**General classification and quality**
- **FR-023**: General (non-rule) classification MUST NOT carry hints that contradict an organization's rules (e.g. the current "Software/IT products → Software" hint), and MUST NOT get worse for items not covered by rules (Appendix A, R4–R10).
- **FR-024**: The reference scenarios (Appendix A) MUST be evaluable automatically, per organization, reporting the assigned group per scenario.
- **FR-025**: Rule matching, precedence, enforcement and tenant isolation MUST be covered by automated tests that do not depend on an external AI service.

### Key Entities

- **Commodity Group**: an accounting category — id, category, name. Global taxonomy (2,000 groups) No organization-specific groups (FR-008).
- **Booking Rule**: belongs to one organization — name, description of covered items, include/exclude example terms, optional conditions (e.g. maximum annualised amount), target commodity group, active flag, change history.
- **Classification Outcome** (per request): the assigned group, its source (`rule` | `system` | `manual` | `override`), the rule applied (if any), the deciding line, and any override reason.
- **Procurement Request / Order Line**: as today; the request carries the single commodity group.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For Acme, reference scenarios R1–R3 and their wording variants are assigned the mandated group in **100 %** of runs (3 runs each), whether uploaded, typed or edited.
- **SC-002**: For Acme, negative scenarios R4–R10 are **never** assigned a rule's target group because of a rule (0 false rule applications over 3 runs each).
- **SC-003**: For Walmart, Schaeffler, Siemens and BMW, **0** rule notes appear and classification of R1–R10 is unchanged versus the baseline.
- **SC-004**: **0** rule-covered Acme requests can be saved by a requester with a different group (UI and programmatic interface).
- **SC-005**: Every buyer/admin override of a rule-determined group has a recorded reason and actor.
- **SC-006**: An Acme admin can add a new booking rule and see it applied to the next request in **under 5 minutes**, without a software change.
- **SC-007**: Determining the commodity group adds no noticeable delay to the request form (rule evaluation within 1 second; no extra wait when no rule applies).

---

## Assumptions

- **"IT Hardware"** means the existing group **29 · Information Technology / Hardware** (no group has the exact name "IT Hardware").
- **"Electrical Engineering"** means the existing group **11 · Facility Management / Electrical Engineering**.
- **Toner scope**: laser/printer toner cartridges, toner kits and drum-and-toner kits; inkjet ink and paper are not covered unless an admin adds them.
- **Subscription scope**: recurring software subscriptions (SaaS, monthly/annual plans, per-seat annual licenses); perpetual licenses and implementation services are not subscriptions.
- **Non-negotiable** means enforced for requesters; buyers and admins may override with a recorded reason (needed to correct a misfiring rule).
- **One group per request** remains; per-line booking is out of scope.
- **Existing requests** are not reclassified automatically (US7 makes deviations visible).
- **Rule language**: rules are written and evaluated for English item descriptions (US quotes).

## Dependencies

- The commodity-group taxonomy and the request form's group selector.
- Task 1 (`specs/001-reliable-quote-extraction/`): correct order lines from uploaded quotes (rules are evaluated on lines).
- Organization settings and roles (admin-only management), activity log (overrides, re-bookings).
- Task 1 §5.5 *"Split classification from extraction"* — booking rules are the natural first step of a separate classification stage.
- Bonus task (approval threshold): FR-009 reuses the $2,000 threshold.

## Out of Scope

- Changing the global taxonomy for all organizations; organization-specific commodity groups.
- Per-line commodity groups / split booking of one request.
- Export to or synchronisation with an accounting system.
- Automatic reclassification of historical requests.
- Rules based on supplier, department or cost centre (only item-based rules in this feature).

---

## Appendix A — Reference scenarios *(ground truth)*

"Today" = commodity group assigned by the **pre-Task-1** extraction for a synthetic one-line quote addressed to Acme Corp (gpt-4o-mini, 2 runs each, 2026-10-22). Catalog references are articles in Acme's seeded catalog.

| # | Item (example wording) | Today | Expected for **Acme** | Expected for **other orgs** | Notes |
| --- | --- | --- | --- | --- | --- |
| R1 | Cable ties nylon 8 in, black, pack of 100 — 20 × $8.50 | 15 Office Equipment ×2 | **11 · Electrical Engineering** (rule a) | normal classification (e.g. Fasteners / Electrical Installation) | Variants that must also match: "zip ties", "tie wraps", "cable tie mounts", "releasable cable ties" |
| R2 | Toner cartridge black, high-yield, HP 59A — 4 × $120.00 | 15 Office Equipment ×2 | **29 · Hardware** (rule b, "IT Hardware") | normal (e.g. 204 Toner Cartridges) | Variants: "laser toner", "toner kit", "drum & toner kit", "TN-2420". Catalog: "Toner cartridge cyan/magenta/yellow/black" (e.g. MON-00922) |
| R3 | Project management tool subscription, monthly, per user — 5 × $12.00 ($720/yr) | 31 Software ×2 | **15 · Office Equipment** (rule c, Acme's "Office Supplies") | normal (31 Software) | Variants: "SaaS plan", "annual per-seat license" under the threshold. Catalog: "Video conferencing license host, annual" $20.35 (e.g. ORI-01729) |
| R4 | ERP enterprise license, annual, 500 seats — $85,000.00 | 31 Software ×2 | normal (31 Software) — **not** rule c (not small) | normal | Boundary test for FR-009 |
| R5 | Patch cable Cat 6, 3 ft, pack of 10 — 5 × $27.99 | 29 Hardware ×2 | normal — **not** rule a | normal | Catalog: FAL-00738, ORI-01742 |
| R6 | Charging cable J1772, 11.5 kW, 16 ft | (not run) | normal — **not** rule a | normal | Catalog: SHO-00572 |
| R7 | Copy paper letter size, 20 lb, case — 3 × $49.00 | 201 Copy Paper ×2 | normal (201) — **not** rule b | normal | |
| R8 | Laser printer, A4, network | (not run) | normal (Hardware / Office Equipment) — **not** rule b as "toner" | normal | "printer" ≠ toner |
| R9 | Research license simulation software, perpetual — $1,877.00 | (not run) | normal — **not** rule c (not a subscription) | normal | Catalog: CRE-00669 |
| R10 | Moss art panel with company logo (Task 1 Greenmantle quote) | (classified by Task 1 flow) | normal — no rule | normal | Regression guard for unrelated items |
| R11 | Mixed: Toner black ×2 ($240.00) + Copy paper ×2 ($98.00) | 15 Office Equipment ×2 | **29 · Hardware** (FR-011: highest-value line is toner) | normal | Explanation names the toner line |
| R12 | Mixed: Cable ties ($170.00) + Toner ($480.00) | (not run) | **29 · Hardware** (FR-011: highest-value line) + advice to split | normal | Two different rules |
| R13 | Small subscription at the boundary: 1 × $1,999.99 / year | (not run) | **15 · Office Equipment** (rule c, below $2,000) | normal | FR-009 boundary |
| R14 | Subscription: 1 × $2,000.00 / year | (not run) | normal (31 Software) — not "small" | normal | FR-009 boundary |

**Tenant check:** signed in as `admin@walmart.com`, R1–R3 receive **no** Acme rule and no rule note.
