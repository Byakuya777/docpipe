import shutil
import uuid
from pathlib import Path
from typing import BinaryIO

from app.config import settings

CHUNK_SIZE = 1024 * 1024


def save_upload(fileobj: BinaryIO, document_id: uuid.UUID, filename: str) -> Path:
    """Persist an uploaded file and return where it landed.

    The name on disk is the document UUID, not the user's filename — two uploads
    called "paper.pdf" must not collide, and a UUID can't contain path
    traversal. The original filename is kept in the document row instead.
    """
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower() or ".pdf"
    destination = settings.storage_dir / f"{document_id}{suffix}"

    fileobj.seek(0)
    with destination.open("wb") as out:
        shutil.copyfileobj(fileobj, out, CHUNK_SIZE)

    return destination
