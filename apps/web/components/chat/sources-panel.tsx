"use client";

import * as React from "react";
import { ChevronDown, Library } from "lucide-react";

import { cn } from "@/lib/utils";
import type { RetrievedSource } from "@/lib/types";

/**
 * Expandable "N sources used" panel, listing every source the retrieve
 * step surfaced (up to 5 — see citation-drawer.tsx for why). Collapsed
 * by default to keep the answer focused; clicking a source opens the
 * same CitationDrawer as clicking an inline [n] link.
 */
export function SourcesPanel({
  sources,
  onSourceClick,
}: {
  sources: RetrievedSource[];
  onSourceClick: (index: number) => void;
}) {
  const [open, setOpen] = React.useState(false);

  if (sources.length === 0) return null;

  return (
    <div className="rounded-lg border border-border">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
        aria-expanded={open}
      >
        <span className="flex items-center gap-1.5">
          <Library className="size-3.5" />
          {sources.length} source{sources.length === 1 ? "" : "s"} used
        </span>
        <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <ul className="flex flex-col gap-0.5 border-t border-border px-2 py-2">
          {sources.map((source, i) => (
            <li key={source.chunk_id}>
              <button
                type="button"
                onClick={() => onSourceClick(i + 1)}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-muted"
              >
                <span className="flex size-4 shrink-0 items-center justify-center rounded bg-primary/15 text-[10px] font-medium text-primary">
                  {i + 1}
                </span>
                <span className="truncate text-muted-foreground">{source.source_ref}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
