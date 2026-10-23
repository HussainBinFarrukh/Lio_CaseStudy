# Contract: Classification & booking rules

camelCase payloads for the classification service (feeds the form like extraction / catalog);
snake_case for rule resources and request outputs (DB rows), per constitution IV.

## `POST /classification` — any organization member

Request: `{"lines": [{"description": str, "quantity": num, "unitPrice": num|null, "totalPrice": num|null}]}` (1–50)

Response 200 (never an error for AI problems):

```json
{
  "commodityGroupId": 29, "commodityGroupName": "Hardware", "source": "rule",
  "rule": {"id": "…", "name": "Printer toner", "targetGroupId": 29,
           "explanation": "Acme Corp booking rule: Printer toner is booked under Hardware (29)."},
  "decidingLine": {"index": 0, "description": "Toner cartridge black, high-yield, HP 59A"},
  "splitAdvice": false,
  "hints": [{"ruleId": "…", "ruleName": "Small software subscriptions", "targetGroupId": 15,
             "lineIndex": 1, "message": "This may fall under Acme Corp's booking rule …"}]
}
```

`source`: `rule` (deterministic rule), `system` (shortlist + model), `null` (nothing found / AI
unavailable).

## Requests — `POST /requests`, `PUT /requests/{id}` (additive input)

| Field | Rule |
| --- | --- |
| `commoditySource` | `"system" | "manual"`, default `manual` — what the client did with the proposal. |
| `bookingRuleId` | Accepted hint: rule of the org whose target = `commodityGroupId`, else 422. |
| `overrideReason` | Required (non-empty) for buyer/admin when the group differs from a rule's target. |

Errors: requester with a group other than a rule's target → **422**
`"Booking rule 'Printer toner' requires commodity group 29 · Hardware."`; buyer/admin without a
reason → **422** `"A reason is required to override booking rule 'Printer toner'."`.

`RequestOut` adds: `commodity_source`, `booking_rule_id`, `booking_rule_name`,
`booking_rule_line`, `override_reason`.

## Booking rules — admin only (`require_org_admin`)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/booking-rules` | List (incl. target group name). |
| POST | `/booking-rules` | Create → 201 `{rule, warnings[]}`; 422 unknown group / empty include / duplicate name. |
| PUT | `/booking-rules/{id}` | Update → `{rule, warnings[]}`; other org's id → 404. |
| DELETE | `/booking-rules/{id}` | 204. |
| GET | `/booking-rules/events` | Audit trail (latest first). |
| GET | `/booking-rules/check` | Requests whose group differs from current rules (no overrides). |
| POST | `/booking-rules/rebook` | `{"requestIds": [...]}` → re-books those (logged); returns count. |

Rule body (snake_case like other admin resources): `name`, `description`, `include_terms`,
`exclude_terms`, `max_annual_amount`, `target_commodity_group_id`, `active`.
Buyers/requesters → 403 on all.
