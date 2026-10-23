# Phase 0 Research: Organization-Specific Commodity Booking Rules

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-10-23

Evidence: two live experiments on this repository (gpt-4o-mini, text-embedding-3-small) with
synthetic one-line quotes addressed to Acme (scripts outside the repo; results below).

## Baseline (this repository, after Task 1)

| Item | Current extraction | Old hints restored (minus "Software → 31") |
| --- | --- | --- |
| R1 cable ties · R2 toner · R3 PM subscription · R4 ERP · R5 patch cable · R6 charging cable · R7 copy paper · R8 laser printer | **none** (all 8) | **15 Office Equipment** (all 8) |
| R9 perpetual software | none | none |

Classification inside the extraction call is effectively broken: the model picks among
2,000 groups at the end of a long Structured-Outputs answer and returns `null`. Restoring the
generic hints over-corrects into group 15 (the effect the spec's context describes). FR-023
("must not get worse") is therefore measured against the *pre-Task-1* baseline in Appendix A.

## R1 — Separate classification stage (FR-003, FR-023, spec dependency "split classification")

**Decision**: classify in its own step, after the order lines are known:

1. **Shortlist**: embed the request's line descriptions (joined) and rank the **base**
   commodity groups (380 groups without a size/tier variant suffix " — …"; variants collapse onto
   their base) by cosine similarity; take the top 12 and always add the general anchors
   **15 Office Equipment, 29 Hardware, 30 IT Services, 31 Software**.
2. **Pick**: `gpt-4o-mini` (Structured Outputs, `temperature=0`) chooses one id from the
   shortlist for the request's primary item, or `null`. Ids outside the shortlist are discarded.

**Evidence** (experiment 2, 13 requests): all 13 got a sensible group — R1 → 327 Fasteners Set,
R2 → 204 Toner Cartridges, R3/R4/R9 → 31 Software, R5 → 245 Network Installation, R6 → 252 EV
Charging Station, R7 → 201 Copy Paper, R8 → 29 Hardware, MacBook → 29 Hardware, grinding machine
→ 45 Production Machinery, moss quotes → 43 / 72. Median 0.53 s. Without collapsing variants and
anchors the shortlist was crowded by "— Standard Pack/Bulk" variants and 3/13 returned `null`.

**Consequences**: the 2,000-group list is removed from the extraction prompt (≈ 20k fewer
prompt tokens per upload); extraction fills `commodityGroupId` by calling this stage, so its
response shape is unchanged.

**Alternatives**: restoring hints in the extraction prompt (everything → 15); full taxonomy in a
separate call (slow, same failure mode); embeddings only (no reliable winner).

## R2 — Booking rules are deterministic term rules (FR-004, FR-006, FR-007)

**Decision**: a rule = include terms + exclude terms + optional `max_annual_amount`, evaluated
in plain code on each order line's description:

- Terms are case-insensitive phrases matched on word boundaries; a trailing `*` matches word
  continuations (`cable tie*` → "cable ties", "cable tie mounts"; `tn-*` → "TN-2420").
- A line is covered when **any include term** matches and **no exclude term** matches.
- `max_annual_amount`: the **annualised** total of the request's lines covered by the rule must
  be **below** the limit (FR-009). A line saying monthly / per month / "/mo" is × 12; otherwise
  the line total counts as annual ($1,999.99 → small, $2,000.00 → not).

**Evidence** (experiment 1b): embedding similarity cannot decide rule membership — "Laser
printer" scores 0.45 against the toner rule while "TN-2420 high yield" scores 0.40; "ERP
enterprise license" 0.57 vs. a real subscription 0.52. Terms make R1–R14 exact and repeatable.

**Seeded Acme rules** (FR-002, FR-021):

| Rule | Include | Exclude | Condition | Target |
| --- | --- | --- | --- | --- |
| Cable ties | `cable tie*`, `zip tie*`, `tie wrap*`, `kabelbinder` | — | — | 11 Electrical Engineering |
| Printer toner | `toner*`, `tn-*` | `ink`, `paper` | — | 29 Hardware ("IT Hardware") |
| Small software subscriptions | `subscription*`, `saas`, `per-seat licen*`, `per seat licen*`, `per user`, `per-user`, `monthly plan`, `annual plan` | `perpetual`, `implementation` | annualised < $2,000 | 15 Office Equipment ("Office Supplies") |

## R3 — Uncertain matches become hints (FR-010)

When no rule covers a line, its embedding is compared with each active rule's text (name,
description, include terms). Similarity **≥ 0.50**, no exclude term, and the amount condition
not already violated → a hint "This may fall under Acme's booking rule '<name>' → <group>" with an
**Apply** action. Never applied silently. Evidence: true variants 0.47–0.71; negatives that would
otherwise trigger (laser printer 0.45, copy paper 0.41, patch cable 0.39) stay below 0.50; ERP
(0.57) is suppressed by its amount; perpetual software by the exclude term. Without the AI
service, hints are simply absent (rules still apply).

## R4 — Mixed requests (FR-011)

Line value = `totalPrice` (or `unitPrice × quantity`). The **highest-value line** decides: if it
is covered by a rule, the rule's group applies (source `rule`); otherwise the system
classification applies. When lines are covered by two different rules → `splitAdvice`. R11
(toner $240 > paper $98) → 29; R12 (toner $480 > ties $170) → 29 + split advice.

## R5 — Enforcement, overrides, provenance (FR-012 – FR-015)

The server re-evaluates rules on every create/update (rules are pure, so no AI cost):

- Rule applies and the group differs → **requester: 422** naming the rule; **buyer/admin:**
  allowed only with a non-empty `overrideReason` → source `override`, activity entry
  "Commodity group overridden … reason …".
- A request already overridden keeps its override while its group is unchanged.
- Stored on the request: `commodity_source` (`rule | system | manual | override`),
  `booking_rule_id` + `booking_rule_name` snapshot, `booking_rule_line` (deciding line),
  `override_reason`. An accepted hint is sent as `bookingRuleId` and stored as source `rule`.

## R6 — Rule storage and management (FR-016 – FR-021)

Org-scoped table `booking_rules` (constitution I/V: an org-scoped table where settings JSON would
be too loose) + `booking_rule_events` audit trail (who / what / when). Admin-only CRUD; target
group must exist; overlapping include terms with another active rule → saved with a warning.
Seed: Acme's three rules keyed by (org, name), inserted only if absent — never overwrites edits.
No org-specific commodity groups (FR-008 clarified → existing group 15).

## R7 — Existing requests (FR-022)

`GET /booking-rules/check` lists the org's requests whose group differs from what current rules
mandate (excluding recorded overrides); `POST /booking-rules/rebook` re-books selected ids, each
with an activity entry. Nothing changes automatically.

## R8 — Tests & evaluation (FR-024, FR-025)

Offline: rule matching for R1–R14 and variants, annualisation, precedence, mixed lines, hints and
classification with stub embedder/LLM, enforcement (requester 422 / buyer override + reason /
admin), tenant isolation (Walmart unaffected), CRUD permissions, seed idempotence, check/rebook.
Live: `scripts/eval_classification.py` runs R1–R14 for Acme and Walmart and prints the assigned
group and source per scenario.

## Post-build measurement (2026-10-23, real seeded rule texts)

Hint similarity with the full rule text (name + description + terms): "CRM user license, yearly" 0.52
and "Design software license, 12 months" 0.51 → hint; "Kabel tie mounts" 0.62 → hint;
"Video conferencing license host, annual" 0.46 → no hint (borderline); "Brother TN2420" (no
hyphen) 0.45 → no hint and no term match — an admin can add a term. Negatives stay below 0.50:
laser printer 0.41, printer paper 0.39, patch cable 0.40, ink 0.37 (also excluded). Threshold
kept at 0.50: lowering it would start hinting printers as toner.
