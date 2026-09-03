import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Batch, BatchStatus, Document, DocumentStatus
from app.db.session import get_db
from app.storage import save_upload
from app.tasks import process_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/batches", tags=["batches"])


@router.post("", status_code=202)
def create_batch(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    """Accept N PDFs, queue one task per document, return immediately.

    The response does not wait for any document to be processed — that is the
    entire point of the architecture. Poll GET /api/batches/{id} for progress.
    """
    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")

    bad = [f.filename for f in files if Path(f.filename or "").suffix.lower() != ".pdf"]
    if bad:
        # Reject the whole batch rather than silently processing part of it —
        # a half-accepted upload is harder to reason about than a clean error.
        raise HTTPException(
            status_code=400,
            detail=f"only .pdf files are supported in v1; rejected: {', '.join(bad)}",
        )

    batch = Batch(total_documents=len(files), status=BatchStatus.PROCESSING)
    db.add(batch)
    db.flush()  # assigns batch.id without ending the transaction

    documents = []
    for upload in files:
        filename = upload.filename or "upload.pdf"
        document_id = uuid.uuid4()
        storage_path = save_upload(upload.file, document_id, filename)
        documents.append(
            Document(
                id=document_id,
                batch_id=batch.id,
                filename=filename,
                storage_path=str(storage_path),
                status=DocumentStatus.QUEUED,
            )
        )

    db.add_all(documents)
    # Commit before enqueueing: a worker can start the instant a task is
    # published and must find its row already there.
    db.commit()

    for doc in documents:
        task = process_document.delay(str(doc.id))
        doc.celery_task_id = task.id
    db.commit()

    logger.info("queued batch %s with %d documents", batch.id, len(documents))
    return {"batch_id": str(batch.id), "total_documents": batch.total_documents}


@router.get("/{batch_id}")
def get_batch(batch_id: uuid.UUID, db: Session = Depends(get_db)):
    """Batch progress. This is what the frontend polls (§9)."""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")

    counts = dict(
        db.execute(
            select(Document.status, func.count())
            .where(Document.batch_id == batch_id)
            .group_by(Document.status)
        ).all()
    )

    documents = db.execute(
        select(Document).where(Document.batch_id == batch_id).order_by(Document.created_at)
    ).scalars().all()

    return {
        "id": str(batch.id),
        "status": batch.status,
        "total_documents": batch.total_documents,
        "completed_count": counts.get(DocumentStatus.DONE, 0),
        "failed_count": counts.get(DocumentStatus.FAILED, 0),
        "created_at": batch.created_at,
        "documents": [
            {"id": str(d.id), "filename": d.filename, "status": d.status} for d in documents
        ],
    }
