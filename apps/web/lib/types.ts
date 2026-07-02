/**
 * Types mirroring apps/api/app/schemas.py.
 *
 * Keep this file in sync with the backend by hand — there's no shared
 * codegen step yet, so any change to a Pydantic model in schemas.py
 * should be reflected here too.
 */

// ─── Documents ──────────────────────────────────────────────────────────────

/**
 * Lifecycle of an ingested document.
 * Mirrors documind_core.models.DocumentStatus.
 */
export type DocumentStatus = "pending" | "ingesting" | "ready" | "failed";

/**
 * Status of a background ingestion job.
 * Mirrors documind_core.models.JobStatus.
 */
export type JobStatus = "queued" | "running" | "completed" | "failed";

/** Response body for POST /documents/upload. */
export interface IngestJobResponse {
  job_id: string;
  doc_id: string;
  filename: string;
  status: string;
  message: string;
}

/** One document row, as returned by GET /documents. */
export interface Document {
  doc_id: string;
  title: string;
  source_path: string;
  status: DocumentStatus;
  chunk_count: number | null;
  page_count: number | null;
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
}

/** Status of a background ingestion job, from GET /documents/{doc_id}/status. */
export interface JobStatusOut {
  job_id: string;
  doc_id: string | null;
  status: JobStatus;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

/** Response body for DELETE /documents/{doc_id}. */
export interface DeleteResponse {
  doc_id: string;
  deleted: boolean;
  message: string;
}

// ─── Chat ───────────────────────────────────────────────────────────────────

/** Request body for POST /chat. */
export interface ChatRequest {
  query: string;
  session_id?: string;
  user_id?: string;
}

/** Which LangGraph node an event refers to. */
export type AgentNode = "plan" | "retrieve" | "generate" | "critic" | "finalize";

/** Emitted when a LangGraph node begins executing. */
export interface NodeStartEvent {
  type: "node_start";
  node: AgentNode;
}

/** Payload shapes for tool_result, keyed by node — mirrors chat.py's _extract_node_data(). */
export interface PlanResultData {
  plan: string;
  sub_queries: string[];
}

export interface RetrievedSource {
  chunk_id: string;
  source_ref: string;
  score: number;
}

export interface RetrieveResultData {
  chunk_count: number;
  sources: RetrievedSource[];
}

export interface GenerateResultData {
  draft_length: number;
  citation_count: number;
}

export interface CriticResultData {
  faithful: boolean;
  fully_cited: boolean;
  gaps: string[];
  loops: number;
}

export type ToolResultData =
  | PlanResultData
  | RetrieveResultData
  | GenerateResultData
  | CriticResultData
  | Record<string, never>; // finalize sends {}

/** Emitted when a node completes, carrying its output payload. */
export interface ToolResultEvent {
  type: "tool_result";
  node: AgentNode;
  data: ToolResultData;
}

/** Emitted for each streamed word of the draft answer. */
export interface TokenEvent {
  type: "token";
  text: string;
}

/** Emitted once, after generation, with the full citation list. */
export interface CitationEvent {
  type: "citation";
  citations: string[];
}

/** Emitted when the graph reaches finalize — the answer is complete. */
export interface FinalEvent {
  type: "final";
  answer: string;
  citations: string[];
  loops: number;
}

/** Emitted if the agent raises an unhandled exception during streaming. */
export interface ErrorEvent {
  type: "error";
  message: string;
}

/**
 * Discriminated union of every SSE event the /chat endpoint can emit.
 * Narrow on `event.type` to get the right payload shape.
 *
 * @example
 *   function handleEvent(event: ChatEvent) {
 *     switch (event.type) {
 *       case "node_start":
 *         return console.log(`${event.node} started`);
 *       case "token":
 *         return appendToDraft(event.text);
 *       case "final":
 *         return console.log(event.answer, event.citations);
 *     }
 *   }
 */
export type ChatEvent =
  | NodeStartEvent
  | ToolResultEvent
  | TokenEvent
  | CitationEvent
  | FinalEvent
  | ErrorEvent;

// ─── Health ─────────────────────────────────────────────────────────────────

export type ServiceHealthStatus = "ok" | "degraded" | "error";

export interface ServiceStatus {
  name: string;
  status: ServiceHealthStatus;
  detail: string | null;
}

/** Response body for GET /health. */
export interface HealthResponse {
  status: ServiceHealthStatus;
  services: ServiceStatus[];
}
