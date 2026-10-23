import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import require_org_admin
from app.db.session import get_db
from app.models import (
    BookingRule,
    BookingRuleEvent,
    CommodityGroup,
    OrganizationMember,
    ProcurementRequest,
    RequestActivity,
)
from app.schemas.booking_rules import (
    BookingRuleEventOut,
    BookingRuleIn,
    BookingRuleOut,
    BookingRuleSaved,
    MisbookedRequest,
    RebookRequest,
    RebookResult,
)
from app.services import booking_rules as engine
from app.services import classification

router = APIRouter(prefix="/booking-rules", tags=["booking-rules"])

_RULE_FIELDS = (
    "name",
    "description",
    "include_terms",
    "exclude_terms",
    "max_annual_amount",
    "target_commodity_group_id",
    "active",
)


def _get_org_rule(db: Session, rule_id: uuid.UUID, organization_id: uuid.UUID) -> BookingRule:
    rule = db.scalar(
        select(BookingRule).where(
            BookingRule.id == rule_id, BookingRule.organization_id == organization_id
        )
    )
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking rule not found")
    return rule


def _rule_out(db: Session, rule: BookingRule) -> BookingRuleOut:
    group = db.get(CommodityGroup, rule.target_commodity_group_id)
    out = BookingRuleOut.model_validate(rule)
    out.target_commodity_group_name = group.name if group else None
    return out


def _snapshot(rule: BookingRule) -> dict:
    """The rule's editable fields, JSON-ready (for the change history)."""
    snapshot = {field: getattr(rule, field) for field in _RULE_FIELDS}
    if snapshot["max_annual_amount"] is not None:
        snapshot["max_annual_amount"] = float(snapshot["max_annual_amount"])
    return snapshot


def _validate(db: Session, organization_id: uuid.UUID, payload: BookingRuleIn, rule_id=None):
    if db.get(CommodityGroup, payload.target_commodity_group_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown commodity group id: {payload.target_commodity_group_id}",
        )
    conditions = [BookingRule.organization_id == organization_id, BookingRule.name == payload.name]
    if rule_id is not None:
        conditions.append(BookingRule.id != rule_id)
    duplicate = db.scalar(select(BookingRule.id).where(*conditions))
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A booking rule named '{payload.name}' already exists.",
        )


def _warnings(db: Session, organization_id: uuid.UUID, rule: BookingRule) -> list[str]:
    others = [r for r in classification.load_rules(db, organization_id) if r.id != rule.id]
    return engine.overlapping_terms(classification.to_engine_rule(rule), others)


def _log(db, membership, rule, action, summary, detail=None) -> None:
    db.add(
        BookingRuleEvent(
            organization_id=membership.organization_id,
            rule_id=rule.id if rule else None,
            actor_id=membership.user_id,
            action=action,
            summary=summary,
            detail=detail,
        )
    )


@router.get("", response_model=list[BookingRuleOut])
def list_rules(
    membership: OrganizationMember = Depends(require_org_admin),
    db: Session = Depends(get_db),
) -> list[BookingRuleOut]:
    rules = db.scalars(
        select(BookingRule)
        .where(BookingRule.organization_id == membership.organization_id)
        .order_by(BookingRule.name)
    )
    return [_rule_out(db, r) for r in rules]


@router.post("", response_model=BookingRuleSaved, status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: BookingRuleIn,
    membership: OrganizationMember = Depends(require_org_admin),
    db: Session = Depends(get_db),
) -> BookingRuleSaved:
    _validate(db, membership.organization_id, payload)
    rule = BookingRule(
        organization_id=membership.organization_id,
        updated_by=membership.user_id,
        **payload.model_dump(),
    )
    db.add(rule)
    db.flush()
    _log(db, membership, rule, "created", f"Created rule '{rule.name}'", {"after": _snapshot(rule)})
    warnings = _warnings(db, membership.organization_id, rule)
    db.commit()
    return BookingRuleSaved(rule=_rule_out(db, rule), warnings=warnings)


@router.put("/{rule_id}", response_model=BookingRuleSaved)
def update_rule(
    rule_id: uuid.UUID,
    payload: BookingRuleIn,
    membership: OrganizationMember = Depends(require_org_admin),
    db: Session = Depends(get_db),
) -> BookingRuleSaved:
    rule = _get_org_rule(db, rule_id, membership.organization_id)
    _validate(db, membership.organization_id, payload, rule_id=rule.id)
    before = _snapshot(rule)
    for field, value in payload.model_dump().items():
        setattr(rule, field, value)
    rule.updated_by = membership.user_id
    db.flush()
    after = _snapshot(rule)
    changed = sorted(k for k in after if before.get(k) != after.get(k))
    if changed:
        _log(
            db,
            membership,
            rule,
            "updated",
            f"Updated rule '{rule.name}': {', '.join(changed)}",
            {"before": before, "after": after},
        )
    warnings = _warnings(db, membership.organization_id, rule)
    db.commit()
    return BookingRuleSaved(rule=_rule_out(db, rule), warnings=warnings)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule_id: uuid.UUID,
    membership: OrganizationMember = Depends(require_org_admin),
    db: Session = Depends(get_db),
) -> None:
    rule = _get_org_rule(db, rule_id, membership.organization_id)
    _log(db, membership, rule, "deleted", f"Deleted rule '{rule.name}'", {"before": _snapshot(rule)})
    db.flush()
    db.delete(rule)
    db.commit()


@router.get("/events", response_model=list[BookingRuleEventOut])
def list_events(
    membership: OrganizationMember = Depends(require_org_admin),
    db: Session = Depends(get_db),
) -> list[BookingRuleEventOut]:
    events = db.scalars(
        select(BookingRuleEvent)
        .where(BookingRuleEvent.organization_id == membership.organization_id)
        .order_by(BookingRuleEvent.created_at.desc())
        .limit(200)
    )
    return [BookingRuleEventOut.model_validate(e) for e in events]


def _misbooked(db: Session, organization_id: uuid.UUID) -> list[tuple[ProcurementRequest, MisbookedRequest]]:
    rules = classification.load_rules(db, organization_id)
    if not rules:
        return []
    requests = db.scalars(
        select(ProcurementRequest)
        .options(selectinload(ProcurementRequest.order_lines))
        .where(ProcurementRequest.organization_id == organization_id)
        .order_by(ProcurementRequest.created_at.desc())
    )
    found = []
    for request in requests:
        if request.commodity_source == "override":
            continue  # deliberately booked elsewhere by a buyer/admin
        lines = [
            engine.Line(
                description=line.position_description,
                quantity=float(line.amount),
                unit_price=float(line.unit_price),
                total_price=float(line.total_price),
            )
            for line in sorted(request.order_lines, key=lambda l_: l_.line_order)
        ]
        outcome = engine.evaluate(rules, lines)
        if outcome.rule and request.commodity_group_id != outcome.rule.target_group_id:
            found.append(
                (
                    request,
                    MisbookedRequest(
                        request_id=request.id,
                        title=request.title,
                        current_group_id=request.commodity_group_id,
                        mandated_group_id=outcome.rule.target_group_id,
                        rule_id=outcome.rule.id,
                        rule_name=outcome.rule.name,
                        deciding_line=lines[outcome.deciding_index].description,
                        created_at=request.created_at,
                    ),
                )
            )
    return found


@router.get("/check", response_model=list[MisbookedRequest])
def check_existing_requests(
    membership: OrganizationMember = Depends(require_org_admin),
    db: Session = Depends(get_db),
) -> list[MisbookedRequest]:
    """Requests whose commodity group differs from what the current rules mandate."""
    return [item for _, item in _misbooked(db, membership.organization_id)]


@router.post("/rebook", response_model=RebookResult)
def rebook_requests(
    payload: RebookRequest,
    membership: OrganizationMember = Depends(require_org_admin),
    db: Session = Depends(get_db),
) -> RebookResult:
    """Re-book selected requests to the group their rule mandates (nothing automatic)."""
    wanted = set(payload.request_ids)
    count = 0
    for request, item in _misbooked(db, membership.organization_id):
        if request.id not in wanted:
            continue
        before = request.commodity_group_id
        request.commodity_group_id = item.mandated_group_id
        request.commodity_source = "rule"
        request.booking_rule_id = item.rule_id
        request.booking_rule_name = item.rule_name
        request.booking_rule_line = item.deciding_line
        request.override_reason = None
        db.add(
            RequestActivity(
                request_id=request.id,
                actor_id=membership.user_id,
                action="rebooked",
                summary=(
                    f"Re-booked to commodity group {item.mandated_group_id} by booking rule "
                    f"'{item.rule_name}'"
                ),
                detail={"from": before, "to": item.mandated_group_id, "rule": item.rule_name},
            )
        )
        count += 1
    db.commit()
    return RebookResult(rebooked=count)
