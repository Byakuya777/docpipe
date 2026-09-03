"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  TERMINAL_BATCH_STATUSES,
  getBatch,
  getDocument,
  type Batch,
  type BatchDocument,
  type DocumentDetail,
} from "@/lib/api";
import { WorkerStrip } from "./WorkerStrip";
import { ResultCard } from "./ResultCard";

const POLL_MS = 2000;

export function BatchProgress({ batchId }: { batchId: string }) {
  const [batch, setBatch] = useState<Batch | null>(null);
  const [results, setResults] = useState<DocumentDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const terminal = batch !== null && TERMINAL_BATCH_STATUSES.includes(batch.status);

  useEffect(() => {
    let cancelled = false;
    let timeout: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      try {
        const next = await getBatch(batchId);
        if (cancelled) return;
        setBatch(next);
        setError(null);

        // Stop once the batch is terminal — §15's "frontend polls forever"
        // pitfall. Scheduling the next tick only on a non-terminal response
        // means there is no interval left running to forget about.
        if (!TERMINAL_BATCH_STATUSES.includes(next.status)) {
          timeout = setTimeout(poll, POLL_MS);
        }
      } catch (e) {
        if (cancelled) return;
        // Stop rather than hammer an endpoint that is already failing.
        setError(e instanceof Error ? e.message : "Could not load this batch.");
      }
    }

    poll();
    return () => {
      cancelled = true;
      if (timeout) clearTimeout(timeout);
    };
  }, [batchId]);

  // Results live on the per-document endpoint, so fetch them once the batch
  // has settled and cannot change again.
  const documentIds = useMemo(
    () => batch?.documents.map((d) => d.id).join(",") ?? "",
    [batch],
  );

  useEffect(() => {
    if (!terminal || !documentIds) return;
    let cancelled = false;

    Promise.all(documentIds.split(",").map(getDocument))
      .then((docs) => {
        if (!cancelled) setResults(docs);
      })
      .catch(() => {
        if (!cancelled) setError("Loaded the batch, but could not load its results.");
      });

    return () => {
      cancelled = true;
    };
  }, [terminal, documentIds]);

  if (error && !batch) {
    return (
      <p className="border-l-2 border-bad pl-4 text-sm text-bad">
        {error} <Link href="/" className="underline">Start a new batch.</Link>
      </p>
    );
  }

  if (!batch) {
    return <p className="font-mono text-sm text-muted">Loading batch…</p>;
  }

  const settled = batch.completed_count + batch.failed_count;
  const percent = batch.total_documents
    ? Math.round((settled / batch.total_documents) * 100)
    : 0;

  return (
    <div className="space-y-8">
      <header>
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
          <h1 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
            {settled} of {batch.total_documents} processed
          </h1>
          <StatusPill status={batch.status} polling={!terminal} />
        </div>

        <div
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Batch progress"
          className="mt-4 h-1.5 w-full bg-line"
        >
          <div
            className={`h-full transition-[width] duration-500 ${
              batch.failed_count && !batch.completed_count ? "bg-bad" : "bg-ink"
            }`}
            style={{ width: `${percent}%` }}
          />
        </div>

        <p className="mt-2 font-mono text-[11px] text-muted">batch {batch.id}</p>
      </header>

      <WorkerStrip documents={batch.documents} />

      <section>
        <h2 className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted">
          Documents
        </h2>
        <ul className="mt-3 divide-y divide-line border-y border-line">
          {batch.documents.map((doc) => (
            <DocumentRow key={doc.id} doc={doc} />
          ))}
        </ul>
      </section>

      {terminal && (
        <section>
          <h2 className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted">
            Results
          </h2>
          {results ? (
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              {results.map((doc) => (
                <ResultCard key={doc.id} doc={doc} />
              ))}
            </div>
          ) : (
            <p className="mt-3 font-mono text-sm text-muted">Loading results…</p>
          )}
        </section>
      )}

      {error && batch && <p className="text-sm text-bad">{error}</p>}
    </div>
  );
}

function DocumentRow({ doc }: { doc: BatchDocument }) {
  const settled = doc.status === "done" || doc.status === "failed";

  return (
    <li className="flex items-center gap-4 py-3">
      <StatusMark status={doc.status} />
      {settled ? (
        <Link
          href={`/documents/${doc.id}`}
          className="flex-1 truncate text-sm underline-offset-4 hover:underline"
        >
          {doc.filename}
        </Link>
      ) : (
        <span className="flex-1 truncate text-sm">{doc.filename}</span>
      )}
      <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
        {doc.status}
      </span>
    </li>
  );
}

function StatusMark({ status }: { status: BatchDocument["status"] }) {
  const styles: Record<BatchDocument["status"], string> = {
    queued: "border-queued",
    processing: "border-signal bg-signal slot-active",
    done: "border-good bg-good",
    failed: "border-bad bg-bad",
  };
  return (
    <span
      aria-hidden
      className={`h-2.5 w-2.5 shrink-0 border ${styles[status]}`}
    />
  );
}

function StatusPill({ status, polling }: { status: Batch["status"]; polling: boolean }) {
  const tone =
    status === "completed" ? "text-good" : status === "failed" ? "text-bad" : "text-signal";
  return (
    <span className={`flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.14em] ${tone}`}>
      {polling && <span className="slot-active h-1.5 w-1.5 rounded-full bg-signal" />}
      {polling ? "polling every 2s" : status}
    </span>
  );
}
