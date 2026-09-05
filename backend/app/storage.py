"""Where uploaded PDFs live between the API writing them and the worker reading them.

Two backends behind one interface:

  local — a directory on disk. Correct only when the API and the worker share a
          filesystem, which under docker-compose they do (both bind-mount
          ./data). Kept as the default so local development needs no cloud
          account and no credentials.

  s3    — any S3-compatible object store; the deploy uses Cloudflare R2.
          Required in production, because Railway attaches a volume to exactly
          one service (Render is the same). The API and the worker are separate
          services, so they cannot share a disk, and every worker read would be
          a FileNotFoundError.

A document's storage_path records which backend wrote it — a bare filesystem
path, or an "s3://bucket/key" URI — and reads dispatch on that rather than on
the current setting, so rows written before a backend switch still resolve.
"""

import logging
import os
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

from app.config import settings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024

S3_SCHEME = "s3://"


class StorageError(Exception):
    """Storage was unreachable or refused the request. May succeed on a retry.

    Network blips and 5xx from the object store. Mirrors LLMError: the task
    retries these with backoff rather than condemning the document.
    """


class StorageNotFound(Exception):
    """The object is genuinely not there. Retrying cannot conjure it.

    Deliberately a sibling of StorageError rather than a subclass, matching
    LLMError/LLMPermanentError — the two land in separate except clauses with
    no ordering trap between them.
    """


def save_upload(fileobj: BinaryIO, document_id: uuid.UUID, filename: str) -> str:
    """Persist an uploaded file and return the storage_path to record on the row.

    The name on disk (or the object key) is the document UUID, not the user's
    filename — two uploads called "paper.pdf" must not collide, and a UUID
    cannot contain path traversal. The original filename is kept in the
    document row instead.
    """
    suffix = Path(filename).suffix.lower() or ".pdf"
    fileobj.seek(0)

    if settings.storage_backend == "s3":
        key = f"{settings.s3_prefix.strip('/')}/{document_id}{suffix}"
        try:
            # upload_fileobj streams and switches to multipart on its own, so a
            # large PDF never lands in memory whole.
            _s3().upload_fileobj(fileobj, settings.s3_bucket, key)
        except _boto_errors() as exc:
            raise StorageError(
                f"upload to s3://{settings.s3_bucket}/{key} failed: {exc}"
            ) from exc
        logger.info("stored %s as s3://%s/%s", filename, settings.s3_bucket, key)
        return f"{S3_SCHEME}{settings.s3_bucket}/{key}"

    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    destination = settings.storage_dir / f"{document_id}{suffix}"
    with destination.open("wb") as out:
        shutil.copyfileobj(fileobj, out, CHUNK_SIZE)
    logger.info("stored %s at %s", filename, destination)
    return str(destination)


@contextmanager
def open_document(storage_path: str) -> Iterator[Path]:
    """Yield a local path for `storage_path`, whatever backend holds it.

    Extraction needs a real file: pdfplumber seeks all over a PDF, and M4's
    memory work depends on walking it page by page rather than holding the
    document in RAM. So an object-store document is streamed to a temp file and
    deleted on the way out, instead of being buffered in memory.

    A local-backend path is yielded untouched — nothing to download, and
    nothing to clean up.
    """
    if not storage_path.startswith(S3_SCHEME):
        yield Path(storage_path)
        return

    bucket, _, key = storage_path[len(S3_SCHEME) :].partition("/")
    if not bucket or not key:
        raise StorageNotFound(f"malformed storage path {storage_path!r}")

    fd, tmp_name = tempfile.mkstemp(prefix="docpipe-", suffix=Path(key).suffix or ".pdf")
    tmp = Path(tmp_name)
    try:
        try:
            with os.fdopen(fd, "wb") as out:
                _s3().download_fileobj(bucket, key, out)
        except _boto_errors() as exc:
            if _is_missing(exc):
                raise StorageNotFound(f"{storage_path} is not in the bucket") from exc
            raise StorageError(f"download of {storage_path} failed: {exc}") from exc
        logger.info("downloaded %s (%d bytes)", storage_path, tmp.stat().st_size)
        yield tmp
    finally:
        # The worker processes documents back to back; a temp file left behind
        # on every one of them fills the container's disk quietly.
        tmp.unlink(missing_ok=True)


def _is_missing(exc: BaseException) -> bool:
    """True when the store said "no such object" rather than "try again"."""
    code = getattr(exc, "response", {}).get("Error", {}).get("Code")
    return code in {"404", "NoSuchKey", "NoSuchBucket"}


@lru_cache(maxsize=1)
def _s3():
    """The S3 client, built on first use.

    Lazy for two reasons. botocore is a heavy import and the local backend
    never needs it — which matters both to the memory ceiling M4 put on worker
    children and to a host that bills per GB of RAM. And a client built in the
    Celery parent would be inherited by every prefork child along with its TLS
    sockets; building it on first use gives each child its own.
    """
    missing = [
        name
        for name, value in (
            ("S3_BUCKET", settings.s3_bucket),
            ("S3_ENDPOINT_URL", settings.s3_endpoint_url),
            ("S3_ACCESS_KEY_ID", settings.s3_access_key_id),
            ("S3_SECRET_ACCESS_KEY", settings.s3_secret_access_key),
        )
        if not value
    ]
    if missing:
        raise StorageError(
            f"STORAGE_BACKEND=s3 but {', '.join(missing)} "
            f"{'is' if len(missing) == 1 else 'are'} not set"
        )

    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
        config=Config(
            signature_version="s3v4",
            # botocore's own retries cover a single blip without burning one of
            # the task's Celery retries; anything worse becomes a StorageError.
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=10,
            read_timeout=60,
        ),
    )


@lru_cache(maxsize=1)
def _boto_errors() -> tuple[type[BaseException], ...]:
    """botocore's exception bases, imported lazily alongside the client."""
    from botocore.exceptions import BotoCoreError, ClientError

    return (BotoCoreError, ClientError)
