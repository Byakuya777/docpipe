import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentStatus
from app.db.session import get_db
from app.storage import save_upload
from app.tasks import process_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", status_code=202)
def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Accept one PDF, queue it, return immediately.

    This handler never touches the PDF's contents or the LLM — it persists the
    file, commits the row, and hands off to Celery (§6.3). The 202 says
    "accepted, not finished": poll GET /api/documents/{id} for the outcome.
    """
    filename = file.filename or "upload.pdf"
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="only .pdf files are supported in v1")

    document_id = uuid.uuid4()
    storage_path = save_upload(file.file, document_id, filename)

    doc = Document(
        id=document_id,
        filename=filename,
        storage_path=str(storage_path),
        status=DocumentStatus.QUEUED,
    )
    db.add(doc)
    # Commit before enqueueing: a worker can pick the task up the instant it is
    # published, and it must find the row already there.
    db.commit()

    task = process_document.delay(str(document_id))
    doc.celery_task_id = task.id
    db.commit()

    logger.info("queued document %s (%s) as task %s", document_id, filename, task.id)
    return {
        "document_id": str(document_id),
        "filename": filename,
        "status": doc.status,
        "task_id": task.id,
    }


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
        }

    return {
        "id": str(doc.id),
        "filename": doc.filename,
        "status": doc.status,
        "attempt_count": doc.attempt_count,
        "error_message": doc.error_message,
        "created_at": doc.created_at,
        "completed_at": doc.completed_at,
        "result": result,
    }
