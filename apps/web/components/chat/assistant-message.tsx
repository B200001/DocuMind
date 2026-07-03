"use client";

import * as React from "react";
import { AlertCircle, RotateCcw, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { AgentTimeline } from "@/components/chat/agent-timeline";
import { SourcesPanel } from "@/components/chat/sources-panel";
import type { AssistantMessageState } from "@/components/chat/types";
import { CitedText } from "@/components/citations/cited-text";
import { CitationDrawer, type SelectedCitation } from "@/components/citations/citation-drawer";
import { parseSourceRef } from "@/lib/parse-source-ref";

export function AssistantMessage({
  message,
  onRetry,
  docTitles,
}: {
  message: AssistantMessageState;
  onRetry: (query: string) => void;
  /** doc_id -> title, resolved from the Library so citations show friendly names. */
  docTitles?: Record<string, string>;
}) {
  const [selectedCitation, setSelectedCitation] = React.useState<SelectedCitation | null>(null);

  function handleCitationClick(index: number) {
    const source = index <= message.sources.length ? message.sources[index - 1] : undefined;
    setSelectedCitation({ index, source });
  }

  const isGenerating = message.status === "streaming" && message.nodeStates.generate === "active";
  const hasStarted = message.status !== "pending";

  const selectedDocTitle =
    selectedCitation?.source && docTitles
      ? docTitles[parseSourceRef(selectedCitation.source.source_ref).docId]
      : undefined;

  return (
    <div className="flex flex-col gap-3">
      {!hasStarted && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Sparkles className="size-3.5 animate-pulse" />
          Thinking&hellip;
        </div>
      )}

      {hasStarted && (
        <AgentTimeline nodeStates={message.nodeStates} loops={message.loops} />
      )}

      {message.draft.length > 0 && (
        <CitedText
          text={message.draft}
          resolvedCount={message.sources.length}
          onCitationClick={handleCitationClick}
          className="whitespace-pre-wrap text-sm leading-relaxed text-foreground"
        />
      )}

      {isGenerating && (
        <span
          aria-hidden
          className="inline-block h-4 w-1.5 animate-pulse rounded-sm bg-foreground/60"
        />
      )}

      {message.sources.length > 0 && (
        <SourcesPanel sources={message.sources} onSourceClick={handleCitationClick} />
      )}

      {message.status === "error" && (
        <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-sm text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <div className="flex flex-1 flex-col gap-2">
            <span>{message.errorMessage ?? "Something went wrong."}</span>
            <Button
              variant="outline"
              size="sm"
              className="w-fit"
              onClick={() => onRetry(message.query)}
            >
              <RotateCcw className="size-3.5" />
              Try again
            </Button>
          </div>
        </div>
      )}

      <CitationDrawer
        citation={selectedCitation}
        onOpenChange={(open) => !open && setSelectedCitation(null)}
        docTitle={selectedDocTitle}
      />
    </div>
  );
}
