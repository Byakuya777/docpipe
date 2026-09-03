import logging
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from app.config import settings

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """The file cannot yield text. Permanent — retrying will not help.

    A corrupt PDF stays corrupt and a scanned PDF stays image-only, so the task
    marks the document `failed` instead of retrying (PROJECT_SPEC.md §6.2).
    """


@dataclass
class Extraction:
    """Extracted text, plus how much of the document it actually covers.

    The page counts are not bookkeeping — extraction stops early on long
    documents, so without them a summary drawn from 12 of 600 pages is
    indistinguishable from one drawn from the whole thing.
    """

    text: str
    pages_read: int
    total_pages: int

    @property
    def truncated(self) -> bool:
        return self.pages_read < self.total_pages


def extract_text(path: Path) -> Extraction:
    """Pull the text out of a PDF.

    Raises ExtractionError for anything unusable so the caller has one
    exception type to catch — a broken file must never take down the worker.
    """
    if not path.exists():
        raise ExtractionError(f"file not found on disk: {path}")

    if path.stat().st_size == 0:
        raise ExtractionError("file is empty (0 bytes)")

    pages: list[str] = []
    chars = 0
    pages_read = 0
    truncated = False
    try:
        with pdfplumber.open(path) as pdf:
            total_pages = len(pdf.pages)
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                # pdfplumber caches parsed objects per page; without this the
                # whole document accumulates in memory as we walk it.
                page.flush_cache()

                pages_read += 1
                if page_text.strip():
                    pages.append(page_text)
                    chars += len(page_text)

                if chars >= settings.extract_max_chars:
                    truncated = True
                    break
    except ExtractionError:
        raise
    except Exception as exc:
        # pdfminer raises a wide and undocumented spread of exception types on
        # malformed input, so this catch stays broad on purpose.
        raise ExtractionError(f"could not parse PDF: {type(exc).__name__}: {exc}") from exc

    if truncated:
        logger.info(
            "stopped extraction at page %d of %d (%d chars, cap %d)",
            pages_read,
            total_pages,
            chars,
            settings.extract_max_chars,
        )

    text = "\n\n".join(p for p in pages if p.strip())
    if not text.strip():
        raise ExtractionError(
            "no extractable text — scanned/image-only PDFs need OCR, "
            "which is out of scope for v1"
        )

    logger.info(
        "extracted %d chars from %d of %d pages of %s",
        len(text),
        pages_read,
        total_pages,
        path.name,
    )
    return Extraction(text=text, pages_read=pages_read, total_pages=total_pages)
