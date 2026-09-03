import Link from "next/link";
import { isPartialCoverage, type DocumentDetail } from "@/lib/api";

export function ResultCard({ doc }: { doc: DocumentDetail }) {
  const failed = doc.status === "failed";

  return (
    <Link
      href={`/documents/${doc.id}`}
      className={`card-in block border bg-surface p-5 transition-colors hover:border-ink ${
        failed ? "border-bad/40" : "border-line"
      }`}
    >
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="truncate font-display text-base font-bold tracking-tight">
          {doc.filename}
        </h3>
        <span
          className={`font-mono text-[10px] uppercase tracking-[0.12em] ${
            failed ? "text-bad" : "text-good"
          }`}
        >
          {doc.status}
        </span>
      </div>

      {failed ? (
        <p className="mt-3 text-sm text-bad">
          {doc.error_message ?? "Processing failed."}
        </p>
      ) : (
        <>
          {doc.result?.key_fields?.title && (
            <p className="mt-2 truncate text-sm text-muted">
              {doc.result.key_fields.title}
            </p>
          )}
          {isPartialCoverage(doc.result) && (
            <p className="mt-3 border-l-2 border-signal pl-2 font-mono text-[11px] text-signal">
              Summarized from the first {doc.result!.pages_read} of{" "}
              {doc.result!.total_pages} pages
            </p>
          )}
          <p className="mt-3 line-clamp-3 text-sm leading-relaxed">
            {doc.result?.summary ?? "No summary recorded."}
          </p>
        </>
      )}

      <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-muted tabular-nums">
        {doc.result?.category && <span>{doc.result.category}</span>}
        {doc.result?.processing_ms != null && (
          <span>{(doc.result.processing_ms / 1000).toFixed(1)}s</span>
        )}
        <span>
          {doc.attempt_count} {doc.attempt_count === 1 ? "attempt" : "attempts"}
        </span>
      </div>
    </Link>
  );
}
