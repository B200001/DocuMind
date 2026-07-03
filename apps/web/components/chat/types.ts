import type { RetrievedSource } from "@/lib/types";

/** The 4 nodes shown in the agent timeline — "finalize" has no chip. */
export type TimelineNode = "plan" | "retrieve" | "generate" | "critic";
export type TimelineNodeState = "pending" | "active" | "done";

export interface UserMessageState {
  id: string;
  role: "user";
  content: string;
}

export interface AssistantMessageState {
  id: string;
  role: "assistant";
  /** The query this turn is answering — kept for "Try again" retries. */
  query: string;
  status: "pending" | "streaming" | "done" | "error";
  nodeStates: Record<TimelineNode, TimelineNodeState>;
  plan: string | null;
  subQueries: string[];
  sources: RetrievedSource[];
  draft: string;
  citations: string[];
  loops: number;
  errorMessage: string | null;
}

export type ChatMessage = UserMessageState | AssistantMessageState;

export function createInitialAssistantMessage(
  id: string,
  query: string
): AssistantMessageState {
  return {
    id,
    role: "assistant",
    query,
    status: "pending",
    nodeStates: { plan: "pending", retrieve: "pending", generate: "pending", critic: "pending" },
    plan: null,
    subQueries: [],
    sources: [],
    draft: "",
    citations: [],
    loops: 0,
    errorMessage: null,
  };
}
