"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getDocument, type DocumentDetail } from "@/lib/api";

export default function DocumentPage() {
  const params = useParams<{ id: string }>();
  const id = typeof params.id === "string" ? params.id : "";

  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    getDocument(id)
      .then((d) => !cancelled && setDoc(d))
      .catch((e) =>
        !cancelled &&
        setError(e instanceof Error ? e.message : "Could not load this document."),
      );
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (error) {
    return (
      <Shell>
        <p className="border-l-2 border-bad pl-4 text-sm text-bad">
          {error} <Link href="/" className="underline">Start a new batch.</Link>
        </p>
      </Shell>
    );
  }

  if (!doc) {
    return (
      <Shell>
        <p className="font-mono text-sm text-muted">Loading document…</p>
      </Shell>
    );
  }

  const fields = doc.result?.key_fields;

  return (
    <Shell>
      <Link
        href={`/batches/${doc.batch_id}`}
        className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted underline-offset-4 hover:underline"
      >
        ← Back to batch
      </Link>

      <header className="mt-4">
        <h1 className="font-display text-3xl font-extrabold tracking-tight">
          {doc.filename}
        </h1>
        <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 font-mono text-[11px] text-muted tabular-nums">
          <Meta label="status" value={doc.status} />
          <Meta label="attempts" value={String(doc.attempt_count)} />
          {doc.result?.model && <Meta label="model" value={doc.result.model} />}
          {doc.result?.processing_ms != null && (
            <Meta label="took" value={`${(doc.result.processing_ms / 1000).toFixed(1)}s`} />
          )}
          {doc.result?.token_count != null && (
            <Meta label="tokens" value={String(doc.result.token_count)} />
          )}
        </dl>
      </header>

      {doc.status === "failed" && (
        <section className="mt-8 border-l-2 border-bad bg-surface p-4">
          <h2 className="font-mono text-[11px] uppercase tracking-[0.14em] text-bad">
            Why it failed
          </h2>
          <p className="mt-2 text-sm">{doc.error_message ?? "No reason recorded."}</p>
        </section>
      )}

      {doc.result && (
        <div className="mt-8 space-y-8">
          <Section title="Summary">
            <p className="text-base leading-relaxed">{doc.result.summary}</p>
          </Section>

          {fields?.title && (
            <Section title="Title">
              <p className="text-base">{fields.title}</p>
            </Section>
          )}

          {fields?.authors && fields.authors.length > 0 && (
            <Section title="Authors">
              <p className="text-base">{fields.authors.join(", ")}</p>
            </Section>
          )}

          {fields?.methodology && (
            <Section title="Methodology">
              <p className="text-base leading-relaxed">{fields.methodology}</p>
            </Section>
          )}

          {fields?.key_findings && fields.key_findings.length > 0 && (
            <Section title="Key findings">
              <ul className="list-disc space-y-1 pl-5 text-base">
                {fields.key_findings.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            </Section>
          )}

          {fields?.datasets && fields.datasets.length > 0 && (
            <Section title="Datasets">
              <p className="text-base">{fields.datasets.join(", ")}</p>
            </Section>
          )}
        </div>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto w-full max-w-3xl px-6 py-12">{children}</div>;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted">
        {title}
      </h2>
      <div className="mt-2">{children}</div>
    </section>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-1.5">
      <dt className="uppercase tracking-[0.12em]">{label}</dt>
      <dd className="text-ink">{value}</dd>
    </div>
  );
}
