"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { createBatch } from "@/lib/api";

function isPdf(file: File) {
  return file.name.toLowerCase().endsWith(".pdf");
}

export function UploadForm() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function addFiles(incoming: FileList | null) {
    if (!incoming) return;
    const accepted = Array.from(incoming).filter(isPdf);
    const rejected = Array.from(incoming).length - accepted.length;

    setNotice(
      rejected > 0
        ? `Skipped ${rejected} file${rejected === 1 ? "" : "s"}. This version reads text-based PDFs only.`
        : null,
    );
    setError(null);
    // De-duplicate by name+size so dropping the same file twice is a no-op.
    setFiles((current) => {
      const seen = new Set(current.map((f) => `${f.name}:${f.size}`));
      return [...current, ...accepted.filter((f) => !seen.has(`${f.name}:${f.size}`))];
    });
  }

  function removeFile(index: number) {
    setFiles((current) => current.filter((_, i) => i !== index));
  }

  async function submit() {
    if (!files.length || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const { batch_id } = await createBatch(files);
      router.push(`/batches/${batch_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
      setSubmitting(false);
    }
  }

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          addFiles(e.dataTransfer.files);
        }}
        className={`border border-dashed px-6 py-12 text-center transition-colors ${
          dragging ? "border-signal bg-signal/5" : "border-line bg-surface"
        }`}
      >
        <p className="font-display text-lg font-bold tracking-tight">
          Drop PDFs here
        </p>
        <p className="mt-1 text-sm text-muted">
          Each file becomes its own background job.
        </p>

        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="mt-5 border border-ink px-4 py-2 text-sm font-medium hover:bg-ink hover:text-paper transition-colors"
        >
          Choose files
        </button>

        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          className="sr-only"
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {notice && <p className="mt-3 text-sm text-signal">{notice}</p>}
      {error && (
        <p className="mt-3 border-l-2 border-bad pl-3 text-sm text-bad">{error}</p>
      )}

      {files.length > 0 && (
        <>
          <ul className="mt-6 divide-y divide-line border-y border-line">
            {files.map((file, i) => (
              <li
                key={`${file.name}:${file.size}:${i}`}
                className="flex items-center gap-4 py-2.5"
              >
                <span className="font-mono text-[11px] text-muted tabular-nums">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="flex-1 truncate text-sm">{file.name}</span>
                <span className="font-mono text-[11px] text-muted tabular-nums">
                  {(file.size / 1024).toFixed(0)} KB
                </span>
                <button
                  type="button"
                  onClick={() => removeFile(i)}
                  aria-label={`Remove ${file.name}`}
                  className="text-muted hover:text-bad transition-colors text-sm px-1"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>

          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            className="mt-6 w-full bg-ink px-5 py-3 font-display text-base font-bold tracking-tight text-paper transition-opacity hover:opacity-90 disabled:opacity-50 sm:w-auto"
          >
            {submitting
              ? "Queueing…"
              : `Queue ${files.length} document${files.length === 1 ? "" : "s"}`}
          </button>
        </>
      )}
    </div>
  );
}
