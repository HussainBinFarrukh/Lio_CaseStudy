from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from app.core.deps import get_current_user
from app.schemas.extraction import PdfParseResponse
from app.services.pdf import extract_text, is_pdf_upload

router = APIRouter(prefix="/pdf", tags=["pdf"])

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB, matches the upload UI's stated limit


@router.post("/parse", response_model=PdfParseResponse, dependencies=[Depends(get_current_user)])
async def parse_pdf(file: UploadFile) -> PdfParseResponse:
    pdf_bytes = await file.read()
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="PDF exceeds the 10MB limit",
        )
    if not is_pdf_upload(file.filename, file.content_type, pdf_bytes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload a PDF file"
        )

    try:
        text = extract_text(pdf_bytes)
    except Exception:  # noqa: BLE001 — any parser failure means "unreadable" to the user
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="We couldn't read this PDF. Please fill in the form manually.",
        )

    return PdfParseResponse(text=text)
