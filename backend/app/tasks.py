import logging
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.config import settings
from app.db.models import Batch, BatchStatus, Document, DocumentStatus, Result
from app.db.session import SessionLocal
from app.services.extract import ExtractionError, extract_text
from app.services.llm import LLMError, LLMPermanentError, analyze_document

logger = logging.getLogger(__name__)


def _backoff_seconds(retries: int) -> float:
    """Exponential backoff with jitter: ~2s, ~4s, ~8s, capped.

    Computed here rather than with Celery's retry_backoff option, which only
    takes effect for autoretry_for and is ignored by a manual self.retry().

    The jitter matters once M2 batching lands: without it, ten documents
    rate-limited at the same instant would retry at the same instant and
    stampede the provider again.
    """
    delay = settings.retry_backoff_base * (2**retries)
    delay = min(delay, settings.retry_backoff_max)
    return random.uniform(delay / 2, delay)


@celery_app.task(
    bind=True,
    name="app.tasks.process_document",
    max_retries=settings.task_max_retries,
    default_retry_delay=10,
)
def process_document(self, document_id: str) -> str:
    """Extract text, analyze it, write a result. One document per task.

    Every exit path leaves the document in a terminal state — `done` or
    `failed` with an error_message. A document must never be left stuck at
    `processing` because the worker hit something unexpected
    (PROJECT_SPEC.md §15).

    Failures split two ways:
      - permanent (ExtractionError): a corrupt PDF stays corrupt, so retrying
        is pure waste — straight to `failed`.
      - recoverable (LLMError): timeouts and rate limits often succeed on a
        second look — retried with backoff, then `failed` once exhausted.
    """
    started = time.perf_counter()

    with SessionLocal() as db:
        doc = db.get(Document, uuid.UUID(document_id))
        if doc is None:
            logger.error("document %s not found; nothing to process", document_id)
            return "missing"

        batch_id = doc.batch_id

        # Idempotency (§6.2): a re-delivered task must not re-run the analysis
        # or overwrite a finished result. The batch check still runs — it is
        # cheap and makes a batch that missed its flip self-healing.
        if doc.status == DocumentStatus.DONE:
            logger.info("document %s already done; skipping", document_id)
            _finalize_batch(db, batch_id)
            return DocumentStatus.DONE

        doc.status = DocumentStatus.PROCESSING
        doc.attempt_count += 1
        doc.error_message = None
        db.commit()

        try:
            extraction = extract_text(Path(doc.storage_path))
            analysis = analyze_document(extraction.text)
        except ExtractionError as exc:
            # Permanent: a corrupt or image-only file will not fix itself.
            logger.warning("extraction failed for %s: %s", document_id, exc)
            _fail(db, doc, f"extraction failed: {exc}")
            _finalize_batch(db, batch_id)
            return DocumentStatus.FAILED
        except LLMPermanentError as exc:
            # Permanent: a bad key or a rejected request fails identically on
            # every attempt, so retrying only wastes time and money.
            logger.error("llm call permanently failed for %s: %s", document_id, exc)
            _fail(db, doc, f"llm call failed: {exc}")
            _finalize_batch(db, batch_id)
            return DocumentStatus.FAILED
        except LLMError as exc:
            attempt = self.request.retries + 1  # retries is 0 on the first run

            # Check the counter BEFORE calling retry. On the final attempt
            # self.retry(exc=...) re-raises that exception rather than
            # scheduling, and because it would be raised from inside this
            # except block, the broad handler below would not catch it — the
            # document would be left stuck at `processing` forever (§15).
            if self.request.retries >= self.max_retries:
                logger.error(
                    "llm call failed for %s on attempt %d; retries exhausted",
                    document_id,
                    attempt,
                )
                _fail(db, doc, f"llm call failed after {attempt} attempts: {exc}")
                _finalize_batch(db, batch_id)
                return DocumentStatus.FAILED

            countdown = _backoff_seconds(self.request.retries)
            logger.warning(
                "llm call failed for %s on attempt %d: %s — retrying in %.1fs",
                document_id,
                attempt,
                exc,
                countdown,
            )
            # attempt_count was already committed at the top of this run, so the
            # attempt stays visible in the DB even though we bail out here.
            raise self.retry(exc=exc, countdown=countdown)
        except Exception as exc:
            logger.exception("unexpected failure processing %s", document_id)
            _fail(db, doc, f"unexpected error: {type(exc).__name__}: {exc}")
            _finalize_batch(db, batch_id)
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
                pages_read=extraction.pages_read,
                total_pages=extraction.total_pages,
            )
        )
        doc.status = DocumentStatus.DONE
        doc.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info("document %s done in %.0f ms", document_id, elapsed_ms)
        _finalize_batch(db, batch_id)
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


def _finalize_batch(db: Session, batch_id: uuid.UUID) -> None:
    """Flip the batch to a terminal status once nothing is left in flight.

    Runs inside every task rather than in a separate polling process (§6.2) —
    one fewer moving part, and the check happens exactly when it can change.

    The batch row is locked with SELECT ... FOR UPDATE *before* counting, which
    is what makes this safe when several documents finish at the same instant.
    Without the lock, two tasks could both count zero remaining and both
    declare themselves last (§15). The lock serializes them: the first wins and
    flips the status, the second finds the batch already terminal and returns.
    """
    batch = db.execute(
        select(Batch).where(Batch.id == batch_id).with_for_update()
    ).scalar_one_or_none()

    if batch is None or batch.status != BatchStatus.PROCESSING:
        db.commit()  # releases the row lock
        return

    counts = dict(
        db.execute(
            select(Document.status, func.count())
            .where(Document.batch_id == batch_id)
            .group_by(Document.status)
        ).all()
    )
    remaining = sum(n for s, n in counts.items() if s not in DocumentStatus.TERMINAL)
    if remaining:
        db.commit()
        return

    failed = counts.get(DocumentStatus.FAILED, 0)
    total = sum(counts.values())
    batch.status = BatchStatus.FAILED if failed == total else BatchStatus.COMPLETED
    db.commit()

    logger.info(
        "batch %s -> %s (%d of %d documents failed)", batch_id, batch.status, failed, total
    )
