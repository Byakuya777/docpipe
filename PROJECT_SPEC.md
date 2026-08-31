# Async Document Intelligence Pipeline — Project Specification

A system where a user uploads a batch of documents, the app immediately hands off processing to background workers running in parallel, and the user watches live progress as each document gets analyzed by an LLM — instead of staring at a frozen screen.

Keep this file as `PROJECT_SPEC.md` in your repo root. Point Claude Code at it at the start of every session.

---

## 1. The problem this demonstrates

Most student AI projects are synchronous: user submits something, the server calls an LLM, the server waits, the server responds. That's fine for one quick call, but it breaks down the moment you have real work to do — dozens of documents, each needing its own analysis. A synchronous approach means either a request that hangs for minutes (browsers and load balancers time out) or processing everything one at a time when it could run in parallel.

**This project's entire point is the plumbing, not the AI.** The LLM call is almost incidental — you could swap it for image resizing or video transcoding and the architecture wouldn't change. What you're proving is that you can design a system where slow work happens in the background, in parallel, reliably, with the user kept informed — which is a real, common requirement in production software that has nothing to do with AI specifically.

**Deliberately not a finance/multi-agent-analysis tool.** Keep the domain here (document processing) rather than "research any topic" — the goal is that nobody looking at this next to a stock-analysis or multi-agent-research tool sees the same shape at a glance. The differentiation should be obvious from the one-line pitch, not just from reading the code closely.

---

## 2. Scope

### In scope (v1)

- Upload a batch of documents (PDFs to start — text extraction is well-supported and simple)
- Queue one background job per document
- Each job: extract text, call an LLM to summarize + classify + extract key fields
- Live progress updates in the frontend as jobs complete
- Results stored in Postgres, viewable per-document and as a batch summary
- Retry logic for failed jobs (an LLM call times out, a malformed PDF, etc.)
- Dockerized, deployed across separate web / API / worker / Redis services

### Explicitly out of scope

- OCR for scanned/image-only PDFs (assume text-based PDFs for v1)
- User accounts / auth (skip unless you want to reuse Supabase auth from AlphaHedge)
- Multiple file types beyond PDF (add .docx/.txt later if time allows)
- Websockets (polling is fine and simpler — see §9)
- Fine-tuning or custom models — use an off-the-shelf LLM API

**Do not expand scope until the milestones in §11 are done.**

---

## 3. Architecture

```
┌──────────────────────────────────────────┐
│  Next.js + TypeScript frontend            │
│  upload UI, live progress, results view   │
└──────────────────┬─────────────────────────┘
                   │ HTTP / JSON
┌──────────────────▼─────────────────────────┐
│  FastAPI (Python)                          │
│  upload endpoint, job status endpoints     │
└───────┬─────────────────────────┬──────────┘
        │ enqueue                 │ read
┌───────▼──────────┐    ┌─────────▼───────────┐
│  Redis            │    │  Postgres           │
│  Celery broker/   │    │  documents, jobs,    │
│  result backend   │    │  results             │
└───────▲──────────┘    └─────────────────────┘
        │ dequeue
┌───────┴──────────────────────────────────┐
│  Celery workers (N processes)             │
│  extract text → call LLM → write result   │
└────────────────────────────────────────────┘
```

**Data flow:** user uploads N files → API saves files, creates a `batch` + N `document` rows, enqueues one Celery task per document, returns immediately with a batch ID → frontend polls `/api/batches/{id}` → each worker independently extracts text, calls the LLM, writes a `result` row, updates the document's status → frontend shows progress climbing → once all documents are done, frontend shows the full batch view.

---

## 4. Repository layout

```
docpipe/
├── PROJECT_SPEC.md
├── CLAUDE.md
├── docker-compose.yml
├── Makefile
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py                # FastAPI app
│   │   ├── config.py
│   │   ├── celery_app.py          # Celery instance + config
│   │   ├── tasks.py               # the actual background task(s)
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   └── session.py
│   │   ├── api/
│   │   │   └── routes/
│   │   │       ├── batches.py
│   │   │       └── documents.py
│   │   ├── services/
│   │   │   ├── extract.py         # PDF text extraction
│   │   │   └── llm.py             # LLM call wrapper
│   │   └── storage.py             # local disk or S3-compatible storage
│   ├── alembic/
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── next.config.js
│   └── src/
│       ├── app/
│       ├── components/
│       │   ├── UploadForm.tsx
│       │   ├── BatchProgress.tsx
│       │   └── ResultCard.tsx
│       └── lib/
│           └── api.ts
└── data/                          # gitignored, local dev file storage
```

---

## 5. Database schema

Postgres. Use Alembic for migrations from the first table.

```sql
CREATE TABLE batch (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_documents INT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'processing'  -- processing | completed | failed
);

CREATE TABLE document (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id        UUID NOT NULL REFERENCES batch(id) ON DELETE CASCADE,
    filename        TEXT NOT NULL,
    storage_path    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',  -- queued|processing|done|failed
    celery_task_id  TEXT,
    error_message   TEXT,
    attempt_count   INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE result (
    document_id     UUID PRIMARY KEY REFERENCES document(id) ON DELETE CASCADE,
    summary         TEXT NOT NULL,
    category        TEXT,
    key_fields      JSONB,           -- flexible extracted fields, e.g. {"dates": [...], "parties": [...]}
    model           TEXT NOT NULL,
    token_count     INT,
    processing_ms   REAL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON document (batch_id, status);
```

`attempt_count` and `error_message` exist so retries are visible and debuggable, not silent.

---

## 6. The background job — what actually needs to be real

This is the part that has to be load-bearing, or the project collapses into "wrapper with extra steps." Build it properly:

### 6.1 Task definition

```python
# app/tasks.py
from app.celery_app import celery_app

@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def process_document(self, document_id: str):
    try:
        # 1. Load document row, mark status='processing'
        # 2. Extract text (app/services/extract.py)
        # 3. Call LLM (app/services/llm.py) — summary, category, key fields
        # 4. Write result row
        # 5. Mark document status='done', completed_at=now()
        # 6. Check if this was the last document in the batch; if so, mark batch 'completed'
        ...
    except SomeRecoverableError as exc:
        self.retry(exc=exc)
    except Exception as exc:
        # mark status='failed', error_message=str(exc) — don't just crash silently
        ...
```

### 6.2 Things that make this genuinely non-trivial — implement all of them

- **Real retries with backoff.** LLM calls time out or rate-limit sometimes. Use Celery's built-in retry with `default_retry_delay`, and cap `max_retries`. Test this by deliberately making the LLM call fail (mock a timeout) and confirming the task retries then eventually marks the document `failed` rather than retrying forever.
- **Idempotency.** If a task is retried, it shouldn't double-write results or double-charge an LLM call unnecessarily where avoidable. Check current status before reprocessing.
- **Batch completion detection.** Something has to notice "all N documents in this batch are done" and flip the batch status. Do this as a check inside each task (query how many documents in the batch are still not-done) rather than a separate polling process — simpler and avoids a second moving part.
- **Concurrency control.** Configure Celery worker concurrency explicitly (e.g., `celery -A app.celery_app worker --concurrency=4`) and be able to explain what that number controls — how many documents process simultaneously.
- **Graceful handling of a genuinely broken file** (corrupted PDF, empty file) — should land in `failed` with a real error message, not crash the worker process.

### 6.3 What NOT to do

Do not call the LLM directly from the FastAPI request handler "for now" and plan to add Celery later — build the queue from day one, even for one document. Retrofitting async architecture onto synchronous code is a different (and less honest) exercise than designing for it. See milestones in §11 — even M1 should go through the queue.

---

## 7. LLM integration

Keep this simple and focused — it is not the impressive part of the project, don't over-invest here.

```python
# app/services/llm.py
def analyze_document(text: str) -> dict:
    # Truncate/chunk text if it exceeds a reasonable token budget
    # Call the LLM with a prompt requesting strict JSON:
    #   {"summary": "...", "category": "...", "key_fields": {...}}
    # Parse defensively — on malformed JSON, retry once with a stricter prompt,
    # then store what you can with category=null rather than crashing the task.
    ...
```

Pick a domain for `key_fields` that makes the demo concrete — e.g., if you process contracts: parties, dates, dollar amounts; if you process research papers: authors, methodology, key findings. Pick one domain and commit, rather than trying to handle arbitrary documents generically — a focused demo is more convincing than a vague one.

Use a cheap model (gpt-4o-mini, Claude Haiku) during development to control cost; the LLM choice is not the point of the project.

---

## 8. API surface

```
POST /api/batches
    multipart form upload, N files
    -> {"batch_id": "...", "total_documents": N}

GET  /api/batches/{id}
    -> {"id", "status", "total_documents", "completed_count", "failed_count",
        "documents": [{"id", "filename", "status"}]}
    This is what the frontend polls.

GET  /api/documents/{id}
    -> {"id", "filename", "status", "result": {"summary", "category", "key_fields"} | null,
        "error_message": null}

GET  /health
```

---

## 9. Frontend

Next.js + TypeScript. Keep it to three views:

1. **Upload** — drag-and-drop or file picker, submit, redirect to the batch progress view.
2. **Batch progress** — poll `GET /api/batches/{id}` every ~2 seconds. Show a progress bar ("6 of 10 processed"), and a list of documents with live status icons (queued/processing/done/failed). Stop polling once status is `completed` or `failed`.
3. **Results** — once done, show each document's summary/category/key fields as cards; click through for the full result.

**Polling, not websockets, for v1.** Simpler to build and debug, and perfectly legitimate for this use case — don't add websocket complexity unless you finish everything else early and want to upgrade it.

---

## 10. Deployment

`docker-compose.yml` with four services: `db` (Postgres), `redis`, `backend` (FastAPI), `worker` (Celery, same image as backend, different entrypoint command), and `frontend`.

```yaml
services:
  db:
    image: postgres:16
  redis:
    image: redis:7
  backend:
    build: ./backend
    command: uvicorn app.main:app --host 0.0.0.0
    depends_on: [db, redis]
  worker:
    build: ./backend        # same image as backend
    command: celery -A app.celery_app worker --concurrency=4
    depends_on: [db, redis]
  frontend:
    build: ./frontend
    depends_on: [backend]
```

`make up` brings up the whole stack locally. Deploy to Railway or Render — both support multi-service docker-compose-style deployments, which matters here because you genuinely need 4+ services running simultaneously (not just a single web dyno).

---

## 11. Milestones

**M0 — Skeleton (half day).** Repo structure, docker-compose with Postgres + Redis up, FastAPI `/health`, a trivial Celery task that just sleeps and logs, confirm a task enqueued from FastAPI actually runs on the worker. This is the single most important milestone — get the queue plumbing proven end-to-end before touching PDFs or LLMs at all.

**M1 — Real pipeline, one document (1 day).** Upload endpoint accepts one file, extracts text, calls the LLM, writes a result, exposes it via GET. No batching yet, no frontend yet — just prove the full chain works for one document via curl/Postman.

**M2 — Batching (1 day).** Multiple files per upload, one task per document, batch status aggregation, retries wired in and actually tested (deliberately break something and confirm retry + failure handling works).

**M3 — Frontend (1.5–2 days).** Upload UI, polling progress view, results view.

**M4 — Robustness (1 day).** Test with a genuinely corrupted PDF, a very large PDF, an LLM timeout (mock it), concurrent batches. Fix what breaks. This milestone is what makes the "background jobs" claim honest rather than only-works-in-the-happy-path.

**M5 — Deploy (1 day).** Docker Compose locally validated, then deployed to Railway/Render with all 4+ services running, live URL.

**M6 — Polish (half day–1 day).** README, benchmark note (how much wall-clock time does parallel processing save vs. sequential on a 10-document batch — this is an easy, concrete number to include), screenshots/demo clip.

**Realistic total: about 1 week of focused work**, given you already know FastAPI, React/Next.js, and LLM API calls from Sightline and AlphaHedge — Celery/Redis orchestration is the only genuinely new territory.

---

## 12. What to actually measure and put in the README

Run the same 10-document batch two ways and report both numbers — this is your version of the "why does the architecture matter" proof:

- **Sequential**: process the 10 documents one after another in a simple loop (a throwaway script, not your real system)
- **Parallel**: through your actual Celery pipeline with concurrency=4

Report wall-clock time for both. This single comparison is what makes "background jobs" a demonstrated engineering decision rather than an assumed one — the same way the filing-diff project needed a C-vs-Python benchmark.

---

## 13. Resume bullets this produces

- Built an asynchronous document-processing pipeline (Next.js/TypeScript, FastAPI, Celery, Redis, Postgres) that queues and parallelizes LLM analysis across a batch of uploaded documents, with live progress tracking and automatic retry on failure.
- Designed the job orchestration layer from scratch — task queuing, worker concurrency, retry/backoff, and batch-completion detection — cutting processing time for a 10-document batch from `A`s (sequential) to `B`s (parallel, concurrency=4).
- Deployed a 4-service system (web, API, background workers, Redis) to [Railway/Render] via Docker Compose.

Fill in the real numbers from §12 once M4 is done.

---

## 14. The 2–3 sentence answer this unlocks

Once built, here's the honest version of the checklist answer from earlier:

> "I built a document-processing pipeline where uploading a batch of files immediately queues one background job per document instead of blocking the request — a Next.js/TypeScript frontend polls for live progress while Celery workers pull jobs off a Redis queue, extract text, and call an LLM to summarize and classify each document in parallel. It's containerized with Docker and deployed across separate web, API, worker, and Redis services on Railway, and processes a 10-document batch roughly `Nx` faster than sequential processing."

---

## 15. Known pitfalls

| Pitfall | Mitigation |
|---|---|
| Building the LLM call synchronously "for now," adding Celery later | Build the queue in M0, before any real feature — see §6.3 |
| Retries that aren't actually tested, just assumed to work | Deliberately break a call in M4 and watch it retry and fail correctly |
| Batch completion never triggers because of a race condition (two tasks finish at nearly the same time) | Query count of non-done documents inside the task itself; use a DB transaction/lock if you see double-completion bugs |
| Frontend polls forever even after completion | Stop polling once status is `completed` or `failed` |
| Worker crashes silently on a bad PDF and the document just hangs at "processing" forever | Wrap extraction in try/except; always transition to `failed` with a message, never leave a document stuck |
| Topic/framing reads too similar to a "multi-agent AI analysis" pitch (AlphaHedge overlap) | Lead your description with the orchestration ("built a job queue system for parallel document processing"), not the AI ("built an AI analysis tool") |
| Docker multi-service deploy is fiddlier than expected | Budget real time for M5; test the compose file locally end-to-end before touching a cloud host |

---

## 16. Working with Claude Code

Create `CLAUDE.md` in the repo root:

```markdown
# Working agreement

- PROJECT_SPEC.md is the source of truth. Re-read it before starting work.
- Work one milestone at a time, in order. M0 (proving the queue works end to
  end with a trivial task) must be done before any PDF or LLM code is written.
- Never wire the LLM call directly into a FastAPI request handler "temporarily."
  The Celery task is the only place that calls the LLM, from the first commit.
- Explain Celery's retry/backoff mechanism to me before implementing it.
- Actually test failure paths (bad file, mocked LLM timeout) — don't just
  assume try/except works, show me it catching a real induced failure.
- Ask before adding a dependency.
- Small commits with real messages.
```

**Session hygiene:** start each session with "Read PROJECT_SPEC.md and CLAUDE.md, tell me what milestone we're on." Ask Claude Code to explain what a Celery worker actually is and how it differs from the FastAPI process before it writes the integration — you'll be asked about this in an interview, and you should be able to explain the difference between a request-handling process and a background worker process without hesitation.

---

## 17. Stack summary

| Layer | Choice |
|---|---|
| Frontend | Next.js, TypeScript |
| API | Python, FastAPI |
| Queue / broker | Redis |
| Background jobs | Celery |
| Database | Postgres |
| LLM | OpenAI or Anthropic API (cheap model for dev) |
| Infra | Docker Compose, Railway or Render |
