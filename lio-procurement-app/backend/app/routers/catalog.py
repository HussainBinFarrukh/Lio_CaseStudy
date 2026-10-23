from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_membership, require_org_admin
from app.db.session import get_db
from app.models import OrderLine, OrganizationMember, ProcurementRequest
from app.schemas.catalog import CatalogUsage, SuggestionsRequest, SuggestionsResponse
from app.services import catalog_search

router = APIRouter(prefix="/catalog", tags=["catalog"])

USAGE_DEFAULT_DAYS = 30


@router.post(
    "/suggestions", response_model=SuggestionsResponse, response_model_by_alias=True
)
def suggest_articles(
    payload: SuggestionsRequest,
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> SuggestionsResponse:
    """Matching catalog articles (negotiated prices) for each order line.

    Only the caller's organization's catalog is searched. Matching problems never
    surface as errors: without the AI service, exact-token matches are returned.
    """
    return catalog_search.suggest(
        db,
        membership.organization_id,
        payload.lines,
        vendor_name=payload.vendor_name,
        vendor_vat_id=payload.vendor_vat_id,
        limit=payload.limit,
    )


@router.get("/usage", response_model=CatalogUsage, response_model_by_alias=True)
def catalog_usage(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    membership: OrganizationMember = Depends(require_org_admin),
    db: Session = Depends(get_db),
) -> CatalogUsage:
    """Agreement usage for the organization: linked share, realised and missed savings."""
    to_date = to_date or datetime.now(timezone.utc).date()
    from_date = from_date or to_date - timedelta(days=USAGE_DEFAULT_DAYS - 1)
    if from_date > to_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'from' must not be after 'to'",
        )
    start = datetime.combine(from_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=timezone.utc)

    rows = db.execute(
        select(OrderLine, ProcurementRequest.id)
        .join(ProcurementRequest, ProcurementRequest.id == OrderLine.request_id)
        .where(
            ProcurementRequest.organization_id == membership.organization_id,
            ProcurementRequest.created_at >= start,
            ProcurementRequest.created_at < end,
        )
    ).all()

    lines = [line for line, _ in rows]
    linked = [line for line in lines if line.article_number]
    realised = sum(
        max(float(line.original_unit_price) - float(line.negotiated_unit_price), 0)
        * float(line.amount)
        for line in linked
        if line.original_unit_price is not None and line.negotiated_unit_price is not None
    )
    missed = sum(float(line.potential_saving or 0) for line in lines if not line.article_number)
    return CatalogUsage(
        from_date=from_date,
        to_date=to_date,
        request_count=len({request_id for _, request_id in rows}),
        line_count=len(lines),
        linked_line_count=len(linked),
        linked_share=round(len(linked) / len(lines), 4) if lines else 0.0,
        realised_savings=round(realised, 2),
        missed_savings=round(missed, 2),
    )
