"use client";

import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import { ChatStreamError, streamChat } from "@/lib/sse";
import type {
  AgentNode,
  CriticResultData,
  PlanResultData,
  RetrieveResultData,
} from "@/lib/types";
import {
  createInitialAssistantMessage,
  type AssistantMessageState,
  type ChatMessage,
  type TimelineNode,
} from "@/components/chat/types";

const TIMELINE_NODES: readonly TimelineNode[] = ["plan", "retrieve", "generate", "critic"];

function isTimelineNode(node: AgentNode): node is TimelineNode {
  return (TIMELINE_NODES as readonly string[]).includes(node);
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isPending, setIsPending] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);

  const patchAssistant = useCallback(
    (
      assistantId: string,
      patch:
        | Partial<AssistantMessageState>
        | ((m: AssistantMessageState) => Partial<AssistantMessageState>)
    ) => {
      setMessages((prev) =>
        prev.map((m) => {
          if (m.id !== assistantId || m.role !== "assistant") return m;
          const p = typeof patch === "function" ? patch(m) : patch;
          return { ...m, ...p };
        })
      );
    },
    []
  );

  const sendMessage = useCallback(
    async (query: string) => {
      const trimmed = query.trim();
      if (!trimmed || isPending) return;

      const userMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content: trimmed,
      };
      const assistantId = crypto.randomUUID();
      const assistantMessage = createInitialAssistantMessage(assistantId, trimmed);

      // Optimistic: both messages appear immediately, before any network call.
      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setIsPending(true);

      const controller = new AbortController();
      controllerRef.current = controller;
      let sawTerminalEvent = false;

      try {
        for await (const event of streamChat(trimmed, { signal: controller.signal })) {
          switch (event.type) {
            case "node_start": {
              const node = event.node;
              patchAssistant(assistantId, (m) =>
                isTimelineNode(node)
                  ? { status: "streaming", nodeStates: { ...m.nodeStates, [node]: "active" } }
                  : { status: "streaming" }
              );
              break;
            }

            case "tool_result": {
              const node = event.node;
              patchAssistant(assistantId, (m) => {
                const nodeStates = isTimelineNode(node)
                  ? { ...m.nodeStates, [node]: "done" as const }
                  : m.nodeStates;

                if (node === "plan") {
                  const data = event.data as PlanResultData;
                  return { nodeStates, plan: data.plan, subQueries: data.sub_queries };
                }
                if (node === "retrieve") {
                  const data = event.data as RetrieveResultData;
                  return { nodeStates, sources: data.sources };
                }
                if (node === "critic") {
                  const data = event.data as CriticResultData;
                  return { nodeStates, loops: data.loops };
                }
                return { nodeStates };
              });
              break;
            }

            case "token":
              patchAssistant(assistantId, (m) => ({ draft: m.draft + event.text }));
              break;

            case "citation":
              patchAssistant(assistantId, { citations: event.citations });
              break;

            case "final":
              sawTerminalEvent = true;
              patchAssistant(assistantId, {
                status: "done",
                draft: event.answer,
                citations: event.citations,
                loops: event.loops,
              });
              break;

            case "error":
              sawTerminalEvent = true;
              patchAssistant(assistantId, {
                status: "error",
                errorMessage: event.message,
              });
              toast.error("The agent hit a problem", { description: event.message });
              break;
          }
        }

        // The stream closed without ever sending "final" or "error" — the
        // connection likely dropped mid-response. Don't leave the message
        // stuck showing a spinner forever.
        if (!sawTerminalEvent) {
          patchAssistant(assistantId, {
            status: "error",
            errorMessage: "The connection closed before a final answer was received.",
          });
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          patchAssistant(assistantId, (m) => ({
            status: "done",
            draft: m.draft || "Generation stopped.",
          }));
        } else if (err instanceof ChatStreamError) {
          patchAssistant(assistantId, { status: "error", errorMessage: err.message });
          toast.error("Couldn't reach the server", { description: err.message });
        } else {
          const message = err instanceof Error ? err.message : "Something went wrong.";
          patchAssistant(assistantId, { status: "error", errorMessage: message });
          toast.error("Something went wrong", { description: message });
        }
      } finally {
        setIsPending(false);
        controllerRef.current = null;
      }
    },
    [isPending, patchAssistant]
  );

  const stop = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  return { messages, isPending, sendMessage, stop };
}
