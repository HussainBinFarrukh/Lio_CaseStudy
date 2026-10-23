import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_membership, require_buyer_or_admin
from app.db.session import get_db
from app.models import (
    Article,
    BookingRule,
    CommodityGroup,
    OrderLine,
    Organization,
    OrganizationMember,
    ProcurementRequest,
    RequestActivity,
    RequestDocument,
    Supplier,
)
from app.schemas.catalog import ArticleSuggestion, SuggestionLineIn
from app.schemas.requests import (
    QUOTE_DETAIL_FIELDS,
    ApprovalDecision,
    RequestActivityOut,
    RequestCreate,
    RequestOut,
    RequestUpdate,
    StatusUpdate,
)
from app.services import booking_rules as rules_engine
from app.services import catalog_matching, catalog_search, classification
from app.services.pdf import is_pdf_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/requests", tags=["requests"])

MAX_PDF_BYTES = 10 * 1024 * 1024

# Human-readable labels for the fields we track in the activity log.
_FIELD_LABELS = {
    "requestor_name": "requestor",
    "title": "title",
    "vendor_name": "vendor",
    "vat_id": "tax ID",
    "commodity_group_id": "commodity group",
    "total_cost": "total cost",
    "department": "department",
    "order_lines": "order lines",
    "quote_number": "quote number",
    "quote_date": "quote date",
    "quote_valid_until": "quote valid-until date",
    "currency": "currency",
    "net_total": "net total",
    "shipping_amount": "shipping",
    "tax_amount": "tax",
    "fees_amount": "fees",
}


def _load_request_options():
    return (
        selectinload(ProcurementRequest.order_lines),
        selectinload(ProcurementRequest.commodity_group),
    )


def _get_org_request(
    db: Session, request_id: uuid.UUID, organization_id: uuid.UUID
) -> ProcurementRequest:
    request = db.scalar(
        select(ProcurementRequest)
        .options(*_load_request_options())
        # Refresh already-loaded relationships (e.g. after an update commit).
        .execution_options(populate_existing=True)
        .where(
            ProcurementRequest.id == request_id,
            ProcurementRequest.organization_id == organization_id,
        )
    )
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found or you do not have permission to access it",
        )
    return request


def _validate_commodity_group(db: Session, commodity_group_id: int) -> None:
    if db.get(CommodityGroup, commodity_group_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown commodity group id: {commodity_group_id}",
        )


def _enforce_required_fields(
    db: Session, organization_id: uuid.UUID, payload: RequestCreate | RequestUpdate
) -> None:
    """Enforce the org's configurable required fields (see OrganizationSettings)."""
    org = db.get(Organization, organization_id)
    required = (org.settings or {}).get("required_fields", []) if org else []
    missing = [field for field in required if not getattr(payload, field, None)]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Missing fields required by your organization: {', '.join(missing)}",
        )


def _log_activity(
    db: Session,
    request_id: uuid.UUID,
    actor_id: uuid.UUID,
    action: str,
    summary: str,
    detail: dict | None = None,
) -> None:
    db.add(
        RequestActivity(
            request_id=request_id,
            actor_id=actor_id,
            action=action,
            summary=summary,
            detail=detail,
        )
    )


def _order_lines_signature(lines) -> list[tuple]:
    return [
        (
            line.position_description,
            float(line.unit_price),
            float(line.amount),
            line.unit,
            float(line.discount_percent or 0),
            float(line.total_price),
            line.catalog_article_id,
        )
        for line in lines
    ]


_SNAPSHOT_FIELDS = (
    "article_number",
    "article_description",
    "article_supplier_name",
    "negotiated_unit_price",
    "article_min_quantity",
    "original_unit_price",
)


def _catalog_alternatives(
    db: Session, organization_id: uuid.UUID, payload: RequestCreate | RequestUpdate
) -> dict[int, ArticleSuggestion]:
    """Cheapest unused catalog alternative per unlinked line (same rules as suggestions).

    Best effort: request creation never fails because matching is unavailable.
    """
    lines = [
        SuggestionLineIn(
            key=str(index),
            description=line.position_description,
            unit=line.unit,
            quantity=line.amount,
            unit_price=line.unit_price,
            discount_percent=line.discount_percent,
            total_price=line.total_price,
            currency=payload.currency or "USD",
        )
        for index, line in enumerate(payload.order_lines)
        if line.catalog_article_id is None and line.position_description.strip()
    ]
    if not lines:
        return {}
    try:
        result = catalog_search.suggest(
            db,
            organization_id,
            lines,
            vendor_name=payload.vendor_name,
            vendor_vat_id=payload.vat_id,
        )
    except Exception:  # alternatives are informational only (FR-027)
        db.rollback()
        logger.exception("Could not compute catalog alternatives")
        return {}
    alternatives = {}
    for line in result.lines:
        best = catalog_matching.best_cheaper_alternative(line.suggestions)
        if best is not None:
            alternatives[int(line.key)] = best
    return alternatives


def _build_order_lines(
    db: Session,
    organization_id: uuid.UUID,
    payload: RequestCreate | RequestUpdate,
    previous: list[OrderLine] | None = None,
) -> list[OrderLine]:
    """Order lines with catalog snapshots filled from the organization's catalog.

    Links are verified server-side (an article of another organization is
    rejected) and the agreement snapshot comes from the catalog, never from the
    client. A line that keeps the article it was already linked to keeps its
    original snapshot, so later catalog changes don't rewrite the request.
    """
    article_ids = {
        line.catalog_article_id for line in payload.order_lines if line.catalog_article_id
    }
    articles = {
        article.id: (article, supplier_name)
        for article, supplier_name in db.execute(
            select(Article, Supplier.name)
            .join(Supplier, Supplier.id == Article.supplier_id)
            .where(Article.id.in_(article_ids), Article.organization_id == organization_id)
        ).all()
    } if article_ids else {}
    if article_ids - articles.keys():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unknown catalog article",
        )
    previous_snapshots = {
        line.catalog_article_id: {f: getattr(line, f) for f in _SNAPSHOT_FIELDS}
        for line in previous or []
        if line.catalog_article_id
    }
    alternatives = _catalog_alternatives(db, organization_id, payload)

    lines = []
    for index, line in enumerate(payload.order_lines):
        order_line = OrderLine(
            position_description=line.position_description,
            unit_price=line.unit_price,
            amount=line.amount,
            unit=line.unit,
            discount_percent=line.discount_percent,
            total_price=line.total_price,
            line_order=index + 1,
        )
        if line.catalog_article_id:
            order_line.catalog_article_id = line.catalog_article_id
            snapshot = previous_snapshots.get(line.catalog_article_id)
            if snapshot is None:
                article, supplier_name = articles[line.catalog_article_id]
                snapshot = {
                    "article_number": article.article_number,
                    "article_description": article.description,
                    "article_supplier_name": supplier_name,
                    "negotiated_unit_price": article.unit_price,
                    "article_min_quantity": article.quantity,
                    "original_unit_price": line.original_unit_price,
                }
            for field, value in snapshot.items():
                setattr(order_line, field, value)
        elif index in alternatives:
            best = alternatives[index]
            order_line.alternative_article_number = best.article_number
            order_line.alternative_supplier_name = best.supplier_name
            order_line.alternative_unit_price = best.unit_price
            order_line.potential_saving = -best.line_effect
        lines.append(order_line)
    return lines


def _comparable(value):
    return float(value) if isinstance(value, (int, float, Decimal)) else value


def _changed_fields(request: ProcurementRequest, payload: RequestUpdate) -> list[str]:
    """Return the field keys whose value differs between the request and payload."""
    changed: list[str] = []
    if request.requestor_name != payload.requestor_name:
        changed.append("requestor_name")
    if request.title != payload.title:
        changed.append("title")
    if request.vendor_name != payload.vendor_name:
        changed.append("vendor_name")
    if (request.vat_id or "") != (payload.vat_id or ""):
        changed.append("vat_id")
    if request.commodity_group_id != payload.commodity_group_id:
        changed.append("commodity_group_id")
    if float(request.total_cost or 0) != float(payload.total_cost or 0):
        changed.append("total_cost")
    if (request.department or "") != (payload.department or ""):
        changed.append("department")
    old_lines = _order_lines_signature(
        sorted(request.order_lines, key=lambda line: line.line_order)
    )
    new_lines = _order_lines_signature(payload.order_lines)
    if old_lines != new_lines:
        changed.append("order_lines")
    # Quote details only count when the client sent them (see update_request).
    for field in QUOTE_DETAIL_FIELDS:
        if field in payload.model_fields_set and _comparable(
            getattr(request, field)
        ) != _comparable(getattr(payload, field)):
            changed.append(field)
    return changed


def _apply_booking_rules(
    db: Session,
    membership: OrganizationMember,
    payload: RequestCreate | RequestUpdate,
    request: ProcurementRequest,
) -> str | None:
    """Enforce the organization's booking rules and record how the group was decided.

    Spec 003: a rule-covered request must use the rule's group. Requesters are
    rejected otherwise; buyers/admins may override with a reason. Returns an
    activity summary when an override was recorded.
    """
    rules = classification.load_rules(db, membership.organization_id)
    lines = [
        rules_engine.Line(
            description=line.position_description,
            quantity=line.amount,
            unit_price=line.unit_price,
            total_price=line.total_price,
        )
        for line in payload.order_lines
    ]
    outcome = rules_engine.evaluate(rules, lines)
    group_id = payload.commodity_group_id
    deciding = (
        lines[outcome.deciding_index].description if outcome.deciding_index is not None else None
    )

    def record(source, rule_id=None, rule_name=None, line=None, reason=None):
        request.commodity_source = source
        request.booking_rule_id = rule_id
        request.booking_rule_name = rule_name
        request.booking_rule_line = line
        request.override_reason = reason

    rule = outcome.rule
    if rule is not None:
        if group_id == rule.target_group_id:
            record("rule", rule.id, rule.name, deciding)
            return None
        if (
            request.commodity_source == "override"
            and request.commodity_group_id == group_id
            and request.booking_rule_id == rule.id
        ):
            return None  # an earlier buyer/admin override stays in place
        target = db.get(CommodityGroup, rule.target_group_id)
        target_label = f"{rule.target_group_id} · {target.name if target else ''}".strip()
        if membership.role not in ("buyer", "admin"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Booking rule '{rule.name}' requires commodity group {target_label}.",
            )
        reason = (payload.override_reason or "").strip()
        if not reason:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"A reason is required to override booking rule '{rule.name}'.",
            )
        record("override", rule.id, rule.name, deciding, reason)
        return (
            f"Commodity group overridden: booking rule '{rule.name}' requires {target_label}, "
            f"booked under {group_id}. Reason: {reason}"
        )

    if payload.booking_rule_id is not None:
        accepted = db.scalar(
            select(BookingRule).where(
                BookingRule.id == payload.booking_rule_id,
                BookingRule.organization_id == membership.organization_id,
            )
        )
        if accepted is None or accepted.target_commodity_group_id != group_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The accepted booking rule does not match the commodity group.",
            )
        record("rule", accepted.id, accepted.name, deciding)
        return None

    if request.commodity_source is not None and request.commodity_group_id == group_id:
        return None  # group unchanged on edit: keep how it was decided
    record(payload.commodity_source)
    return None


@router.get("", response_model=list[RequestOut])
def list_requests(
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[RequestOut]:
    requests = db.scalars(
        select(ProcurementRequest)
        .options(*_load_request_options())
        .where(ProcurementRequest.organization_id == membership.organization_id)
        .order_by(ProcurementRequest.created_at.desc())
    )
    return [RequestOut.model_validate(r) for r in requests]


@router.get("/{request_id}", response_model=RequestOut)
def get_request(
    request_id: uuid.UUID,
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> RequestOut:
    return RequestOut.model_validate(
        _get_org_request(db, request_id, membership.organization_id)
    )


@router.post("", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
def create_request(
    payload: RequestCreate,
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> RequestOut:
    _validate_commodity_group(db, payload.commodity_group_id)
    _enforce_required_fields(db, membership.organization_id, payload)

    # Vendor fields are already cleaned up during extraction, so we can persist
    # them directly here.
    request = ProcurementRequest(
        user_id=membership.user_id,
        requestor_name=payload.requestor_name,
        title=payload.title,
        vendor_name=payload.vendor_name,
        vat_id=payload.vat_id,
        commodity_group_id=payload.commodity_group_id,
        total_cost=payload.total_cost,
        department=payload.department,
        organization_id=membership.organization_id,
        created_by=membership.user_id,
        status="open",
        **{field: getattr(payload, field) for field in QUOTE_DETAIL_FIELDS},
    )
    request.order_lines = _build_order_lines(db, membership.organization_id, payload)
    override = _apply_booking_rules(db, membership, payload, request)
    db.add(request)
    db.flush()
    linked = sum(1 for line in request.order_lines if line.article_number)
    summary = "Request created"
    if linked:
        summary += (
            f" — {linked} of {len(request.order_lines)} lines use catalog agreements"
        )
    _log_activity(db, request.id, membership.user_id, "created", summary)
    if override:
        _log_activity(db, request.id, membership.user_id, "commodity_override", override)
    db.commit()

    request = _get_org_request(db, request.id, membership.organization_id)
    return RequestOut.model_validate(request)


@router.put("/{request_id}", response_model=RequestOut)
def update_request(
    request_id: uuid.UUID,
    payload: RequestUpdate,
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> RequestOut:
    request = _get_org_request(db, request_id, membership.organization_id)
    _validate_commodity_group(db, payload.commodity_group_id)
    _enforce_required_fields(db, membership.organization_id, payload)

    changed = _changed_fields(request, payload)
    # Rules are checked against the request as it was (an existing override stays).
    override = _apply_booking_rules(db, membership, payload, request)

    request.requestor_name = payload.requestor_name
    request.title = payload.title
    request.vendor_name = payload.vendor_name
    request.vat_id = payload.vat_id
    request.commodity_group_id = payload.commodity_group_id
    request.total_cost = payload.total_cost
    request.department = payload.department
    # Quote details are optional on update: clients that don't send them (e.g.
    # the detail-page edit form) must not wipe what was captured at creation.
    for field in QUOTE_DETAIL_FIELDS:
        if field in payload.model_fields_set:
            setattr(request, field, getattr(payload, field))

    # Replace order lines (same semantics as the original delete-and-insert).
    request.order_lines = _build_order_lines(
        db, membership.organization_id, payload, previous=list(request.order_lines)
    )

    if changed:
        labels = [_FIELD_LABELS.get(f, f) for f in changed]
        _log_activity(
            db,
            request.id,
            membership.user_id,
            "updated",
            f"Updated {', '.join(labels)}",
            {"changed_fields": changed},
        )
    if override:
        _log_activity(db, request.id, membership.user_id, "commodity_override", override)
    db.commit()

    request = _get_org_request(db, request_id, membership.organization_id)
    return RequestOut.model_validate(request)


@router.patch("/{request_id}/status", response_model=RequestOut)
def update_status(
    request_id: uuid.UUID,
    payload: StatusUpdate,
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> RequestOut:
    request = _get_org_request(db, request_id, membership.organization_id)

    if request.status != payload.status:
        _log_activity(
            db,
            request.id,
            membership.user_id,
            "status_changed",
            f"Status changed from {request.status} to {payload.status}",
            {"from": request.status, "to": payload.status},
        )
        request.status = payload.status
        db.commit()

    request = _get_org_request(db, request_id, membership.organization_id)
    return RequestOut.model_validate(request)


@router.patch("/{request_id}/approval", response_model=RequestOut)
def decide_approval(
    request_id: uuid.UUID,
    payload: ApprovalDecision,
    membership: OrganizationMember = Depends(require_buyer_or_admin),
    db: Session = Depends(get_db),
) -> RequestOut:
    """Approve or reject a pending request (buyers and admins only)."""
    request = _get_org_request(db, request_id, membership.organization_id)

    if request.approval_status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request has already been {request.approval_status}.",
        )

    request.approval_status = payload.decision
    request.approved_by = membership.user_id
    request.approved_at = datetime.now(timezone.utc)
    _log_activity(
        db,
        request.id,
        membership.user_id,
        payload.decision,
        f"Request {payload.decision}",
    )
    db.commit()

    request = _get_org_request(db, request_id, membership.organization_id)
    return RequestOut.model_validate(request)


@router.get("/{request_id}/activity", response_model=list[RequestActivityOut])
def get_activity(
    request_id: uuid.UUID,
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[RequestActivityOut]:
    _get_org_request(db, request_id, membership.organization_id)  # scope check
    activity = db.scalars(
        select(RequestActivity)
        .where(RequestActivity.request_id == request_id)
        .order_by(RequestActivity.created_at.desc())
    )
    return [RequestActivityOut.model_validate(a) for a in activity]


@router.put("/{request_id}/document", status_code=status.HTTP_204_NO_CONTENT)
async def upload_document(
    request_id: uuid.UUID,
    file: UploadFile,
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> None:
    """Attach (or replace) the original PDF for a request."""
    request = _get_org_request(db, request_id, membership.organization_id)

    content = await file.read()
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="PDF exceeds the 10MB limit",
        )
    if not is_pdf_upload(file.filename, file.content_type, content):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload a PDF file"
        )

    document = db.scalar(
        select(RequestDocument).where(RequestDocument.request_id == request.id)
    )
    if document is None:
        document = RequestDocument(request_id=request.id)
        db.add(document)
    document.filename = file.filename or "document.pdf"
    document.content_type = "application/pdf"
    document.content = content

    _log_activity(
        db,
        request.id,
        membership.user_id,
        "document_attached",
        f"Attached document {document.filename}",
    )
    db.commit()


@router.get("/{request_id}/document")
def get_document(
    request_id: uuid.UUID,
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> Response:
    _get_org_request(db, request_id, membership.organization_id)  # scope check
    document = db.scalar(
        select(RequestDocument).where(RequestDocument.request_id == request_id)
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No document attached"
        )
    return Response(
        content=document.content,
        media_type=document.content_type,
        headers={"Content-Disposition": f'inline; filename="{document.filename}"'},
    )


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_request(
    request_id: uuid.UUID,
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> None:
    request = _get_org_request(db, request_id, membership.organization_id)
    db.delete(request)  # order lines, activity, document cascade
    db.commit()
