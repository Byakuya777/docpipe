import { CONCURRENCY, type BatchDocument } from "@/lib/api";

/**
 * The queue, drawn.
 *
 * Documents waiting on the left, the worker pool in the middle, finished work
 * on the right. Each slot is one unit of `--concurrency`, so what you see is
 * the architecture's central claim: at most four documents move at once, and
 * the rest wait their turn.
 *
 * Nothing here is simulated — the documents currently in a slot are exactly
 * those the API reports as `processing`.
 */
export function WorkerStrip({
  documents,
  idle = false,
}: {
  documents: BatchDocument[];
  idle?: boolean;
}) {
  const inFlight = documents.filter((d) => d.status === "processing");
  const queued = documents.filter((d) => d.status === "queued").length;
  const done = documents.filter((d) => d.status === "done").length;
  const failed = documents.filter((d) => d.status === "failed").length;

  const slots = Array.from({ length: CONCURRENCY }, (_, i) => inFlight[i] ?? null);

  return (
    <section
      aria-label="Worker pool"
      className="border border-line bg-surface px-5 py-4"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <Tally label="queued" value={idle ? "—" : queued} />

        <Rule />

        <ol className="flex flex-1 gap-2" aria-label="Worker slots">
          {slots.map((doc, i) => (
            <li key={i} className="flex-1">
              <Slot doc={doc} index={i} idle={idle} />
            </li>
          ))}
        </ol>

        <Rule />

        <div className="flex gap-5 sm:gap-4">
          <Tally label="done" value={idle ? "—" : done} tone="good" />
          <Tally label="failed" value={idle ? "—" : failed} tone={failed ? "bad" : "muted"} />
        </div>
      </div>
    </section>
  );
}

function Slot({
  doc,
  index,
  idle,
}: {
  doc: BatchDocument | null;
  index: number;
  idle: boolean;
}) {
  const label = `Worker ${index + 1}`;

  if (!doc) {
    return (
      <div
        title={`${label}: idle`}
        className="h-14 border border-dashed border-line px-2 flex items-center justify-center"
      >
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted">
          {idle ? `w${index + 1}` : "idle"}
        </span>
      </div>
    );
  }

  return (
    <div
      title={`${label}: ${doc.filename}`}
      className="slot-active h-14 border border-signal bg-signal/10 px-2 flex flex-col items-center justify-center gap-0.5 overflow-hidden"
    >
      <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-signal">
        w{index + 1}
      </span>
      <span className="max-w-full truncate text-[11px] text-ink">{doc.filename}</span>
    </div>
  );
}

function Rule() {
  return <div className="hidden sm:block h-px w-6 bg-line" aria-hidden />;
}

function Tally({
  label,
  value,
  tone = "muted",
}: {
  label: string;
  value: number | string;
  tone?: "muted" | "good" | "bad";
}) {
  const toneClass =
    tone === "good" ? "text-good" : tone === "bad" ? "text-bad" : "text-muted";
  return (
    <div className="flex items-baseline gap-2 sm:flex-col sm:items-start sm:gap-0">
      <span className={`font-display text-xl font-bold tabular-nums ${toneClass}`}>
        {value}
      </span>
      <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted">
        {label}
      </span>
    </div>
  );
}
