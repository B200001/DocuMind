/**
 * Typed client for the FastAPI backend (apps/api).
 *
 * All JSON endpoints go through request(), which normalises the two
 * failure modes into a single ApiError:
 *   - network failure (server down / wrong port)  -> status 0
 *   - HTTP error       (4xx/5xx with a JSON body) -> status + detail
 *
 * The streaming /chat endpoint is NOT here — see lib/sse.ts.
 */

import type {
  DeleteResponse,
  Document,
  HealthResponse,
  IngestJobResponse,
  JobStatus,
  JobStatusOut,
} from "@/lib/types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | undefined;

  constructor(status: number, detail: string | undefined, fallbackMessage: string) {
    super(detail ?? fallbackMessage);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, init);
  } catch (cause) {
    // Re-throw aborts untouched so callers can distinguish "user cancelled"
    // from "server unreachable".
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(
      0,
      undefined,
      `Could not reach the API at ${API_URL}. Is the backend running?`
    );
  }

  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = await response.json();
      detail =
        typeof body?.detail === "string"
          ? body.detail
          : body?.detail !== undefined
            ? JSON.stringify(body.detail)
            : undefined;
    } catch {
      // Non-JSON error body — fall through to the generic message.
    }
    throw new ApiError(
      response.status,
      detail,
      `Request to ${path} failed with HTTP ${response.status}.`
    );
  }

  return response.json() as Promise<T>;
}

// ─── Documents ──────────────────────────────────────────────────────────────

export function listDocuments(init?: RequestInit): Promise<Document[]> {
  return request<Document[]>("/documents", { cache: "no-store", ...init });
}

export function uploadDocument(file: File, init?: RequestInit): Promise<IngestJobResponse> {
  const form = new FormData();
  form.append("file", file);
  // No Content-Type header: the browser sets multipart boundaries itself.
  return request<IngestJobResponse>("/documents/upload", {
    method: "POST",
    body: form,
    ...init,
  });
}

export function getDocumentStatus(docId: string, init?: RequestInit): Promise<JobStatusOut> {
  return request<JobStatusOut>(`/documents/${encodeURIComponent(docId)}/status`, {
    cache: "no-store",
    ...init,
  });
}

export function deleteDocument(docId: string): Promise<DeleteResponse> {
  return request<DeleteResponse>(`/documents/${encodeURIComponent(docId)}`, {
    method: "DELETE",
  });
}

// ─── Health ─────────────────────────────────────────────────────────────────

export function fetchHealth(init?: RequestInit): Promise<HealthResponse> {
  return request<HealthResponse>("/health", { cache: "no-store", ...init });
}

// ─── Ingestion status polling ───────────────────────────────────────────────

const TERMINAL_STATUSES: readonly JobStatus[] = ["completed", "failed"];
const POLL_INTERVAL_MS = 1_200;
const POLL_TIMEOUT_MS = 15 * 60_000; // large PDFs on a local CPU can be slow
const MAX_CONSECUTIVE_POLL_ERRORS = 5;

function abortableSleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new Error("Polling aborted."));
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    function onAbort() {
      clearTimeout(timer);
      reject(new Error("Polling aborted."));
    }
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Poll GET /documents/{id}/status until the ingestion job reaches a
 * terminal state ("completed" | "failed"), then return that final status.
 *
 * - onUpdate fires on every successful poll so the UI can advance a stepper.
 * - Transient network blips are tolerated (up to 5 in a row) — a laptop
 *   dropping Wi-Fi for a second shouldn't fail an otherwise healthy upload.
 * - Aborting the signal rejects with Error("Polling aborted.").
 */
export async function pollDocumentStatus(
  docId: string,
  {
    signal,
    onUpdate,
    intervalMs = POLL_INTERVAL_MS,
    timeoutMs = POLL_TIMEOUT_MS,
  }: {
    signal?: AbortSignal;
    onUpdate?: (status: JobStatusOut) => void;
    intervalMs?: number;
    timeoutMs?: number;
  } = {}
): Promise<JobStatusOut> {
  const startedAt = Date.now();
  let consecutiveErrors = 0;

  while (true) {
    if (signal?.aborted) throw new Error("Polling aborted.");
    if (Date.now() - startedAt > timeoutMs) {
      throw new ApiError(
        0,
        undefined,
        "Ingestion is taking too long. Check the Library later — it may still finish."
      );
    }

    try {
      const status = await getDocumentStatus(docId, { signal });
      consecutiveErrors = 0;
      onUpdate?.(status);
      if (TERMINAL_STATUSES.includes(status.status)) return status;
    } catch (err) {
      if (signal?.aborted) throw new Error("Polling aborted.");
      consecutiveErrors += 1;
      if (consecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) throw err;
    }

    await abortableSleep(intervalMs, signal);
  }
}
