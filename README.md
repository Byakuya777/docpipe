# docpipe

A job queue for parallel document processing. Upload a batch of PDFs and the API
hands the work straight to background workers and returns immediately — one
Celery task per document, running four at a time, with live progress in the
browser instead of a hung request.

The LLM call is almost incidental. Swap it for image resizing or video
transcoding and the architecture is unchanged. What this project demonstrates is
the plumbing: queueing, worker concurrency, retry and backoff, batch-completion
detection, and failure handling that survives a corrupted file or a killed
worker.

## The number

The same 10-document batch, processed two ways:

| | Wall clock |
| --- | --- |
| Sequential (a plain loop, one document at a time) | **22.84s** |
| Parallel (this pipeline, worker concurrency 4) | **6.40s** |
| | **3.57× faster** |

Median of three runs each; spread on the parallel side was 0.09s.

Per-document cost is 2.28s, so four workers at full utilisation would finish in
~5.71s. Reaching 6.40s is about **89% parallel efficiency** — the remainder is
the multipart upload, a database row per document, a Redis round trip per task,
and the poll interval. The sequential baseline skips all of that, so the measured
speedup is a floor, not a flattering best case.

Reproduce it with `python scripts/benchmark.py --runs 3` (see [below](#running-the-benchmark)).

## Architecture

```
┌──────────────────────────────────────────┐
│  Next.js + TypeScript frontend           │
│  upload, live progress, results          │
└──────────────────┬───────────────────────┘
                   │ HTTP / JSON
┌──────────────────▼───────────────────────┐
│  FastAPI                                 │
│  upload endpoint, batch/document status  │
└───────┬──────────────────────┬───────────┘
        │ enqueue              │ read
┌───────▼──────────┐  ┌────────▼───────────┐
│  Redis           │  │  Postgres          │
│  Celery broker   │  │  batch, document,  │
│  + result backend│  │  result            │
└───────▲──────────┘  └────────────────────┘
        │ dequeue
┌───────┴──────────────────────────────────┐
│  Celery workers (concurrency 4)          │
│  extract text → call LLM → write result  │
└──────────────────────────────────────────┘
```

Uploading N files creates a `batch` and N `document` rows, enqueues one task per
document, and returns a batch ID immediately. The frontend polls
`GET /api/batches/{id}` every two seconds and stops once the batch is terminal.

## What makes the job real

The queue exists from the first commit — the LLM is never called from a request
handler. Beyond that, the parts that took the actual work:

**Retries with backoff, split by cause.** Failures are classified rather than
lumped together. A corrupt PDF, a rejected API request, or an object missing from
storage is *permanent* — the document fails on attempt 1 rather than burning
retries on something that cannot succeed. A timeout, a rate limit, or a briefly
unreachable object store is *recoverable* — retried up to three times with
exponential backoff and jitter, then failed with the real error recorded. The
jitter matters: without it, ten documents rate-limited at the same instant would
retry at the same instant.

**Idempotency.** A redelivered task checks document status before reprocessing,
so it neither re-runs the analysis nor overwrites a finished result.

**Batch completion without a second moving part.** Each task, on finishing, locks
the batch row with `SELECT … FOR UPDATE` before counting unfinished documents.
The lock is what makes it correct when several documents finish at the same
instant — without it, two tasks could both count zero remaining and both declare
themselves last.

**No document is ever stranded.** Every exit path leaves the document `done` or
`failed` with a message. A worker killed mid-task is handled by `task_acks_late`
plus `task_reject_on_worker_lost`, with Redis's `visibility_timeout` lowered from
its 3600s default to 300s — `acks_late` alone left a killed task's document stuck
at `processing` for an hour. Verified by `SIGKILL`ing a worker mid-document and
watching the document recover with `attempt_count=2`.

**Bounded memory under load.** Four 600-page PDFs at concurrency 4 originally
drove the worker to 6.33GB and got a child OOM-killed. Extraction now stops once
it has enough text and flushes pdfplumber's per-page cache as it goes; peak
memory for that case is **540MB**, the batch finishes in 17s instead of dying,
and a single 600-page PDF went from 66s to 11.5s. When extraction does stop
early, the result records `pages_read`/`total_pages` and the UI says "summarized
from the first N of M pages" — a summary drawn from 12 of 600 pages should not
look like one drawn from the whole document.

## Quick start

```bash
cp .env.example .env      # add ANTHROPIC_API_KEY
make up                   # Postgres, Redis, API, worker, frontend
```

Then open http://localhost:3000. Uploads land on a shared bind mount
(`STORAGE_BACKEND=local`), so no cloud account is needed for local development.

## Running the benchmark

```bash
python scripts/make_bench_corpus.py     # generates data/bench/ (gitignored)
python scripts/benchmark.py --runs 3
```

`scripts/bench_sequential.py` is the baseline: a plain loop that extracts text
and calls the LLM once per document, with no queue, database, or upload. It runs
inside the *worker* container rather than the backend, because `ANTHROPIC_API_KEY`
is scoped to the only service that calls the LLM.

Discard the first run — cold prefork children and first TLS handshakes cost about
two seconds.

## The frontend

Three views, polling rather than websockets:

- **Upload** — file picker, submits the batch, redirects to progress.
- **Batch progress** — a progress bar, per-document status, and a worker strip
  that draws the queue itself: documents waiting on the left, four worker slots
  in the middle, finished work on the right. The slots are exactly the documents
  the API reports as `processing`, so the concurrency limit is visible rather
  than asserted.
- **Result** — summary, category, and extracted fields per document.

The browser only ever talks to the Next server, which proxies `/api/*` onward, so
there is no CORS configuration anywhere.

## Analysis

Documents are treated as research papers — one domain, committed to, rather than
a vague general-purpose extractor. Each result carries a summary, a category, and
`key_fields` of title, authors, methodology, key findings, and datasets. Model
output is parsed defensively: malformed JSON is retried once with a stricter
prompt, then stored with what could be salvaged rather than crashing the task.

Runs on `claude-haiku-4-5`. The model choice is not the point of the project.

## Deployment

Deployed to Railway across five services — frontend, API, worker, Postgres, Redis
— with uploads in Cloudflare R2, because Railway attaches a volume to exactly one
service and the API and worker cannot share a disk.

[DEPLOY.md](DEPLOY.md) is the runbook, including the things that actually broke:
Config as Code being closed to new services, `railway down` silently doing
nothing, Railway's `DATABASE_URL` arriving with a driver-less scheme, and Next.js
baking the proxy target in at build time.

The demo instance is paused between sessions to control cost; restarting it is
three commands.

## Scope

Deliberately not included: OCR for scanned PDFs (they fail with a clear message),
auth, file types beyond PDF, and websockets — polling is simpler and sufficient
here.

## Stack

Next.js · TypeScript · FastAPI · Celery · Redis · Postgres · SQLAlchemy · Alembic
· pdfplumber · Anthropic API · Docker Compose · Railway · Cloudflare R2
