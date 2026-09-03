import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.celery_app import celery_app
from app.db.models import Document, DocumentStatus, Result
from app.db.session import SessionLocal
from app.services.extract import ExtractionError, extract_text
from app.services.llm import LLMError, analyze_document

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="app.tasks.process_document")
def process_document(self, document_id: str) -> str:
    """Extract text, analyze it, write a result. One document per task.

    Every exit path leaves the document in a terminal state — `done` or
    `failed` with an error_message. A document must never be left stuck at
    `processing` because the worker hit something unexpected
    (PROJECT_SPEC.md §15).

    Retries are M2. The recoverable/permanent split is already made below so
    wiring self.retry() in is a one-line change per branch.
    """
    started = time.perf_counter()

    with SessionLocal() as db:
        doc = db.get(Document, uuid.UUID(document_id))
        if doc is None:
            logger.error("document %s not found; nothing to process", document_id)
            return "missing"

        # Idempotency (§6.2): a re-delivered task must not re-run the analysis
        # or overwrite a finished result.
        if doc.status == DocumentStatus.DONE:
            logger.info("document %s already done; skipping", document_id)
            return DocumentStatus.DONE

        doc.status = DocumentStatus.PROCESSING
        doc.attempt_count += 1
        doc.error_message = None
        db.commit()

        try:
            text = extract_text(Path(doc.storage_path))
            analysis = analyze_document(text)
        except ExtractionError as exc:
            # Permanent: a corrupt or image-only file will not fix itself.
            logger.warning("extraction failed for %s: %s", document_id, exc)
            _fail(db, doc, f"extraction failed: {exc}")
            return DocumentStatus.FAILED
        except LLMError as exc:
            # Recoverable in principle (timeout, rate limit) — M2 retries this.
            logger.warning("llm call failed for %s: %s", document_id, exc)
            _fail(db, doc, f"llm call failed: {exc}")
            return DocumentStatus.FAILED
        except Exception as exc:
            logger.exception("unexpected failure processing %s", document_id)
            _fail(db, doc, f"unexpected error: {type(exc).__name__}: {exc}")
            return DocumentStatus.FAILED

        elapsed_ms = (time.perf_counter() - started) * 1000

        # merge() upserts on the primary key, so a reprocessed document
        # replaces its result rather than colliding with it.
        db.merge(
            Result(
                document_id=doc.id,
                summary=analysis.summary,
                category=analysis.category,
                key_fields=analysis.key_fields,
                model=analysis.model,
                token_count=analysis.token_count,
                processing_ms=elapsed_ms,
            )
        )
        doc.status = DocumentStatus.DONE
        doc.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info("document %s done in %.0f ms", document_id, elapsed_ms)
        return DocumentStatus.DONE


def _fail(db, doc: Document, message: str) -> None:
    """Record a terminal failure, even if the session is already broken."""
    db.rollback()
    doc = db.get(Document, doc.id)
    if doc is None:
        return
    doc.status = DocumentStatus.FAILED
    doc.error_message = message[:2000]
    doc.completed_at = datetime.now(timezone.utc)
    db.commit()
