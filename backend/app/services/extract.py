import logging
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """The file cannot yield text. Permanent — retrying will not help.

    A corrupt PDF stays corrupt and a scanned PDF stays image-only, so the task
    marks the document `failed` instead of retrying (PROJECT_SPEC.md §6.2).
    """


def extract_text(path: Path) -> str:
    """Pull the text out of a PDF.

    Raises ExtractionError for anything unusable so the caller has one
    exception type to catch — a broken file must never take down the worker.
    """
    if not path.exists():
        raise ExtractionError(f"file not found on disk: {path}")

    if path.stat().st_size == 0:
        raise ExtractionError("file is empty (0 bytes)")

    pages: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
    except ExtractionError:
        raise
    except Exception as exc:
        # pdfminer raises a wide and undocumented spread of exception types on
        # malformed input, so this catch stays broad on purpose.
        raise ExtractionError(f"could not parse PDF: {type(exc).__name__}: {exc}") from exc

    text = "\n\n".join(p for p in pages if p.strip())
    if not text.strip():
        raise ExtractionError(
            "no extractable text — scanned/image-only PDFs need OCR, "
            "which is out of scope for v1"
        )

    logger.info("extracted %d chars from %d pages of %s", len(text), len(pages), path.name)
    return text
