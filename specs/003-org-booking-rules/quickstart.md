# Quickstart: validating booking rules

Contract: [classification-and-rules-api.md](./contracts/classification-and-rules-api.md). Ground
truth: spec Appendix A (also `backend/tests/fixtures/booking_reference.json`).

## 1. Start

```bash
cd lio-procurement-app && docker compose up --build -d   # migrates 0009, seeds Acme's 3 rules, embeds groups
```

## 2. Offline checks

```bash
cd backend && python -m pytest -q
cd frontend && npx tsc --noEmit && npm run build
```

## 3. Live evaluation

```bash
cd backend && python scripts/eval_classification.py --runs 3
```

Expected: Acme R1 → 11, R2 → 29, R3 → 15, R11/R12 → 29 (+ split advice on R12), R13 → 15,
R14 → normal; R4–R10 never a rule's target *because of a rule*; Walmart: no rule anywhere.

## 4. UI walkthrough

| Who | Do | Expect |
| --- | --- | --- |
| requester@acme.com | New Request, line "Toner cartridge black, high-yield, HP 59A", 4 × $120 | Group **Hardware (29)**, note "Acme Corp booking rule: Printer toner …", selector locked |
| requester@acme.com | Line "Cable ties nylon 8 in, black, pack of 100" | **Electrical Engineering (11)** |
| requester@acme.com | Line "Project management tool subscription, monthly, per user", 5 × $12 | **Office Equipment (15)** |
| requester@acme.com | Line "CRM user license, yearly", $600 | Normal group + hint "may fall under … Small software subscriptions" with **Apply rule** |
| buyer@acme.com | Edit a toner request's group | Allowed only with a reason; activity shows the override |
| admin@acme.com | Organization → Booking rules: add "Label printer tape" → 15 | Next "label printer tape" line gets 15; history shows the change |
| admin@acme.com | Booking rules → Check existing requests | Lists mis-booked requests; **Re-book** fixes selected ones |
| admin@walmart.com | Same toner line | Normal classification (e.g. 204 Toner Cartridges), no rule note |
