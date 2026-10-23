from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_membership
from app.db.session import get_db
from app.models import OrganizationMember
from app.schemas.booking_rules import ClassificationOut, ClassificationRequest
from app.services import classification

router = APIRouter(prefix="/classification", tags=["classification"])


@router.post("", response_model=ClassificationOut, response_model_by_alias=True)
def classify_lines(
    payload: ClassificationRequest,
    membership: OrganizationMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ClassificationOut:
    """Commodity group for a request's lines: the organization's booking rules
    first (deterministic), otherwise a system proposal, plus hints for lines
    that may fall under a rule. Never errors for AI problems."""
    return classification.classify(db, membership.organization_id, payload.lines)
