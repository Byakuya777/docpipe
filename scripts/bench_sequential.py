"""Sequential baseline for the benchmark (PROJECT_SPEC.md §12).

Deliberately NOT the real system: no queue, no Redis, no Postgres, no upload.
Just a loop that extracts text and calls the LLM once per document, which is the
naive shape this project's architecture exists to beat.

That asymmetry is the point, and it runs *against* the result we want: the
sequential path skips the upload, the database writes, the broker round trips
and the status polling that the Celery path pays for. Any speedup measured here
is therefore a floor, not a flattering best case.

Run it inside the *worker* container. It has the same image as the backend, but
ANTHROPIC_API_KEY is scoped to the worker — the only service that calls the LLM
— so the backend cannot run this:

    docker compose exec -T worker python - /app/data/bench < scripts/bench_sequential.py

Prints one JSON object on stdout so the orchestrator can parse it.
"""

import json
import sys
import time
from pathlib import Path

from app.services.extract import extract_text
from app.services.llm import analyze_document


def main() -> None:
    corpus = Path(sys.argv[1] if len(sys.argv) > 1 else "/app/data/bench")
    pdfs = sorted(corpus.glob("*.pdf"))
    if not pdfs:
        print(json.dumps({"error": f"no PDFs in {corpus}"}))
        raise SystemExit(1)

    per_document = []
    started = time.perf_counter()
    for path in pdfs:
        doc_started = time.perf_counter()
        extraction = extract_text(path)
        analyze_document(extraction.text)
        per_document.append(
            {"file": path.name, "ms": round((time.perf_counter() - doc_started) * 1000)}
        )
    elapsed = time.perf_counter() - started

    print(json.dumps({
        "mode": "sequential",
        "documents": len(pdfs),
        "elapsed_s": round(elapsed, 2),
        "per_document": per_document,
    }))


if __name__ == "__main__":
    main()
