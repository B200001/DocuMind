"use client";

import { cn } from "@/lib/utils";

export function CitationLink({
  index,
  resolved,
  onClick,
}: {
  index: number;
  /** Whether we have source metadata for this index (see AssistantMessage). */
  resolved: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`View source ${index}`}
      className={cn(
        "mx-0.5 inline-flex h-4 min-w-4 translate-y-[-1px] items-center justify-center rounded px-1 align-middle text-[10px] font-medium transition-colors",
        resolved
          ? "bg-primary/15 text-primary hover:bg-primary/25"
          : "bg-muted text-muted-foreground hover:bg-muted/70"
      )}
    >
      {index}
    </button>
  );
}
