# Data Model: Organization-Specific Commodity Booking Rules

All changes additive — migration `0009_booking_rules`.

## `booking_rules` (new, org-scoped)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `organization_id` | UUID FK `organizations` `CASCADE`, indexed | Tenant isolation (FR-016). |
| `name` | Text | Unique per organization. |
| `description` | Text | What items the rule covers (shown to admins and in hints). |
| `include_terms` | JSON list[str] | ≥ 1; phrases, trailing `*` = word continuation. |
| `exclude_terms` | JSON list[str] | Optional. |
| `max_annual_amount` | Numeric(12,2) NULL | Annualised total of covered lines must be **below** it (FR-009). |
| `target_commodity_group_id` | Integer FK `commodity_groups` | Must exist (FR-019). |
| `active` | Boolean, default true | Inactive rules are ignored. |
| `created_at`, `updated_at` | timestamptz | `TimestampMixin`. |
| `updated_by` | UUID FK `users` `SET NULL` | |

## `booking_rule_events` (new, append-only audit — FR-020)

`id`, `organization_id` (FK CASCADE), `rule_id` (FK `SET NULL`), `actor_id` (FK users
`SET NULL`), `action` (`created | updated | deleted`), `summary` (Text), `detail` (JSON: before /
after), `created_at`.

## `procurement_requests` — classification outcome (FR-015)

| Column | Type | Notes |
| --- | --- | --- |
| `commodity_source` | String NULL, CHECK in (`rule`,`system`,`manual`,`override`) | NULL for pre-existing rows. |
| `booking_rule_id` | UUID FK `booking_rules` `SET NULL` | |
| `booking_rule_name` | Text | Snapshot (survives rule deletion). |
| `booking_rule_line` | Text | Description of the deciding line. |
| `override_reason` | Text | Required when source = `override`. |

## `commodity_groups` — shortlist embeddings

`embedding` (LargeBinary), `embedding_model` (String) — for the classification shortlist; filled
by `python -m app.embed_catalog` (extended) or lazily.

## Transient

- **RuleMatch**: rule, line index, line description.
- **RuleOutcome**: `rule | None`, `deciding_line_index`, `mandated_group_id`, `split_advice`,
  `covered`: list of (line index → rule).
- **Hint**: rule id/name, target group, line index, message.
- **Classification**: `commodity_group_id`, `source` (`rule` | `system` | `None`), rule info,
  deciding line, split advice, hints.

## State rules

| Situation | Requester save | Buyer/Admin save |
| --- | --- | --- |
| No rule covers the deciding line | any group (source `system`/`manual`) | same |
| Rule covers it, group = target | OK, source `rule` | OK, source `rule` |
| Rule covers it, group ≠ target | **422** naming the rule | OK only with `overrideReason` → `override`, logged |
| Existing `override`, group unchanged | OK (override kept) | OK |
| Hint accepted (`bookingRuleId`, group = target) | OK, source `rule` | OK |
