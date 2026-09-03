import { UploadForm } from "@/components/UploadForm";
import { WorkerStrip } from "@/components/WorkerStrip";

export default function UploadPage() {
  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-14">
      <section className="max-w-2xl">
        <h1 className="font-display text-4xl font-extrabold leading-[1.05] tracking-tight sm:text-5xl">
          Hand off a stack of papers.
          <br />
          Get the tab back immediately.
        </h1>
        <p className="mt-5 text-base leading-relaxed text-muted">
          Every PDF you upload becomes its own background job. The request returns
          as soon as the work is queued, and four workers pull documents off the
          queue in parallel — so a batch takes as long as its slowest few
          documents, not the sum of all of them.
        </p>
      </section>

      <div className="mt-10">
        <UploadForm />
      </div>

      <div className="mt-14">
        <h2 className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted">
          The pipeline
        </h2>
        <div className="mt-3">
          <WorkerStrip documents={[]} idle />
        </div>
        <p className="mt-3 text-sm text-muted">
          Queue a batch to watch documents move through these slots.
        </p>
      </div>
    </div>
  );
}
