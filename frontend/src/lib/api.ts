// All requests are same-origin: next.config.ts rewrites /api/* to FastAPI.

export type DocumentStatus = "queued" | "processing" | "done" | "failed";
export type BatchStatus = "processing" | "completed" | "failed";

export const TERMINAL_BATCH_STATUSES: BatchStatus[] = ["completed", "failed"];

/** Worker concurrency, matching `--concurrency=4` in docker-compose.yml. */
export const CONCURRENCY = 4;

export interface BatchDocument {
  id: string;
  filename: string;
  status: DocumentStatus;
}

export interface Batch {
  id: string;
  status: BatchStatus;
  total_documents: number;
  completed_count: number;
  failed_count: number;
  created_at: string;
  documents: BatchDocument[];
}

/** Research-paper fields, per the domain the backend commits to. */
export interface KeyFields {
  title?: string | null;
  authors?: string[] | null;
  methodology?: string | null;
  key_findings?: string[] | null;
  datasets?: string[] | null;
}

export interface DocumentResult {
  summary: string;
  category: string | null;
  key_fields: KeyFields | null;
  model: string;
  token_count: number | null;
  processing_ms: number | null;
  /** How much of the document the analysis saw. Null for results written
   *  before page coverage was recorded — unknown, not "all of it". */
  pages_read: number | null;
  total_pages: number | null;
}

/** True only when we positively know the analysis missed pages. */
export function isPartialCoverage(result: DocumentResult | null): boolean {
  if (!result || result.pages_read == null || result.total_pages == null) return false;
  return result.pages_read < result.total_pages;
}

export interface DocumentDetail {
  id: string;
  batch_id: string;
  filename: string;
  status: DocumentStatus;
  attempt_count: number;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  result: DocumentResult | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { cache: "no-store", ...init });

  if (!response.ok) {
    // FastAPI puts the reason in `detail`; surface it instead of a bare status.
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON error body — keep the status-based message.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<T>;
}

export function createBatch(
  files: File[],
): Promise<{ batch_id: string; total_documents: number }> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  return request("/api/batches", { method: "POST", body: form });
}

export function getBatch(id: string): Promise<Batch> {
  return request<Batch>(`/api/batches/${id}`);
}

export function getDocument(id: string): Promise<DocumentDetail> {
  return request<DocumentDetail>(`/api/documents/${id}`);
}
