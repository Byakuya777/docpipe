import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Document
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

# Uploading happens through POST /api/batches — a single file is just a batch
# of one. M1's POST /api/documents was scaffolding toward that and is gone.


@router.get("/{document_id}")
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")

    result = None
    if doc.result is not None:
        result = {
            "summary": doc.result.summary,
            "category": doc.result.category,
            "key_fields": doc.result.key_fields,
            "model": doc.result.model,
            "token_count": doc.result.token_count,
            "processing_ms": doc.result.processing_ms,
            "pages_read": doc.result.pages_read,
            "total_pages": doc.result.total_pages,
        }

    return {
        "id": str(doc.id),
        "batch_id": str(doc.batch_id),
        "filename": doc.filename,
        "status": doc.status,
        "attempt_count": doc.attempt_count,
        "error_message": doc.error_message,
        "created_at": doc.created_at,
        "completed_at": doc.completed_at,
        "result": result,
    }
