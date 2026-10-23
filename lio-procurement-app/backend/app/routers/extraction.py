from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_membership
from app.db.session import get_db
from app.models import Organization, OrganizationMember, Profile
from app.schemas.extraction import ExtractionRequest, ExtractionResponse
from app.schemas.organizations import OrganizationSettings
from app.services.extraction import extract_vendor_data

router = APIRouter(prefix="/extraction", tags=["extraction"])


@router.post("", response_model=ExtractionResponse, response_model_by_alias=True)
def extract(
    payload: ExtractionRequest,
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ExtractionResponse:
    """Extract structured vendor data from PDF text via OpenAI.

    Returns ``{success, data?, error?, errorCode?, missingFields?}`` — errors are
    part of the payload, not HTTP errors, so the UI can show partial-extraction
    warnings. Requires an organization: its name and configured aliases tell the
    extractor who the buyer is, so the buyer is never taken as the vendor.
    """
    org = db.get(Organization, membership.organization_id)
    org_settings = OrganizationSettings(**(org.settings or {}))
    profile = db.get(Profile, membership.user_id)
    return extract_vendor_data(
        payload.text,
        db,
        buyer_names=[org.name, *org_settings.buyer_aliases],
        # Department is the requester's own, never read from the quote.
        department=(profile.department or "") if profile else "",
        organization_id=org.id,
    )
