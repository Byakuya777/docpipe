"""Sequential vs parallel wall-clock benchmark (PROJECT_SPEC.md §12).

Runs the same corpus two ways and reports wall-clock time for each:

  sequential — a plain loop (scripts/bench_sequential.py), run inside the
               worker container. No queue, no database, no upload.
  parallel   — the real pipeline: POST the batch to the API, which enqueues one
               Celery task per document, then poll until the batch is terminal.

Both call the same model on the same documents, so the difference is the
architecture and nothing else.

The comparison is deliberately unkind to the parallel side. Its wall clock
includes the multipart upload, a database row per document, a Redis round trip
per task, and the poll interval; the sequential loop pays none of that. The
measured speedup is a floor.

    python scripts/benchmark.py --runs 3

Requires the local stack to be up (`make up`) and the LLM configured.
"""

import argparse
import json
import mimetypes
import statistics
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

POLL_INTERVAL = 0.2  # keeps timing resolution well under a second


def run_sequential(corpus: Path, container_corpus: str, container: str) -> dict:
    script = Path(__file__).with_name("bench_sequential.py").read_bytes()
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", container, "python", "-", container_corpus],
        input=script, capture_output=True,
    )
    out = proc.stdout.decode(errors="replace").strip()
    for line in reversed(out.splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError(
        f"sequential run produced no JSON (exit {proc.returncode})\n"
        f"stdout: {out[-500:]}\nstderr: {proc.stderr.decode(errors='replace')[-500:]}"
    )


def _multipart(pdfs: list[Path]) -> tuple[bytes, str]:
    """Build a multipart/form-data body by hand, to keep timing free of extra deps."""
    boundary = f"----docpipe{uuid.uuid4().hex}"
    body = bytearray()
    for path in pdfs:
        ctype = mimetypes.guess_type(path.name)[0] or "application/pdf"
        body += f"--{boundary}\r\n".encode()
        body += (
            f'Content-Disposition: form-data; name="files"; filename="{path.name}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode()
        body += path.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def run_parallel(corpus: Path, api: str) -> dict:
    pdfs = sorted(corpus.glob("*.pdf"))
    body, content_type = _multipart(pdfs)

    started = time.perf_counter()
    req = urllib.request.Request(
        f"{api}/api/batches", data=body,
        headers={"Content-Type": content_type}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        created = json.loads(resp.read())
    batch_id = created["batch_id"]
    upload_s = time.perf_counter() - started

    while True:
        with urllib.request.urlopen(f"{api}/api/batches/{batch_id}", timeout=30) as resp:
            status = json.loads(resp.read())
        if status["status"] in ("completed", "failed"):
            break
        time.sleep(POLL_INTERVAL)
    elapsed = time.perf_counter() - started

    return {
        "mode": "parallel",
        "documents": len(pdfs),
        "elapsed_s": round(elapsed, 2),
        "upload_s": round(upload_s, 2),
        "batch_id": batch_id,
        "batch_status": status["status"],
        "completed": status["completed_count"],
        "failed": status["failed_count"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--corpus", type=Path, default=Path("data/bench"))
    ap.add_argument("--container-corpus", default="/app/data/bench")
    # The worker, not the backend: ANTHROPIC_API_KEY is deliberately scoped to
    # the only service that calls the LLM, so the baseline has to run there too.
    ap.add_argument("--container", default="worker")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--concurrency", type=int, default=4, help="worker concurrency, for the report only")
    args = ap.parse_args()

    n = len(sorted(args.corpus.glob("*.pdf")))
    if n == 0:
        raise SystemExit(f"no PDFs in {args.corpus} — run scripts/make_bench_corpus.py first")

    print(f"corpus: {n} documents from {args.corpus}")
    print(f"runs:   {args.runs} of each mode\n")

    seq, par = [], []
    for i in range(1, args.runs + 1):
        s = run_sequential(args.corpus, args.container_corpus, args.container)
        seq.append(s["elapsed_s"])
        print(f"  run {i}  sequential  {s['elapsed_s']:6.2f}s")

        p = run_parallel(args.corpus, args.api)
        par.append(p["elapsed_s"])
        flag = "" if p["failed"] == 0 else f"  !! {p['failed']} FAILED"
        print(f"  run {i}  parallel    {p['elapsed_s']:6.2f}s   "
              f"({p['completed']}/{p['documents']} ok, upload {p['upload_s']:.2f}s){flag}")

    s_med, p_med = statistics.median(seq), statistics.median(par)
    print("\n" + "=" * 58)
    print(f"  documents            {n}")
    print(f"  worker concurrency   {args.concurrency}")
    print(f"  sequential (median)  {s_med:6.2f}s   runs: {seq}")
    print(f"  parallel   (median)  {p_med:6.2f}s   runs: {par}")
    print(f"  speedup              {s_med / p_med:6.2f}x")
    print("=" * 58)
    print("\nThe parallel figure includes upload, one DB row per document, a Redis")
    print("round trip per task, and the poll interval. The sequential loop pays")
    print("none of that, so the speedup above is a floor.")


if __name__ == "__main__":
    main()
