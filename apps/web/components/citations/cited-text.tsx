"use client";

import * as React from "react";

import { CitationLink } from "@/components/citations/citation-link";
import { splitOnCitations } from "@/components/citations/parse-citations";

/**
 * Renders answer text with [n] markers replaced by clickable citation
 * links. Re-parses the full text on every render (see parse-citations.ts
 * for why this is the robust choice during streaming).
 */
export function CitedText({
  text,
  resolvedCount,
  onCitationClick,
  className,
}: {
  text: string;
  /** Citations with index <= resolvedCount have source metadata available. */
  resolvedCount: number;
  onCitationClick: (index: number) => void;
  className?: string;
}) {
  const parts = React.useMemo(() => splitOnCitations(text), [text]);

  return (
    <p className={className}>
      {parts.map((part, i) =>
        part.type === "text" ? (
          <React.Fragment key={i}>{part.value}</React.Fragment>
        ) : (
          <CitationLink
            key={i}
            index={part.index}
            resolved={part.index <= resolvedCount}
            onClick={() => onCitationClick(part.index)}
          />
        )
      )}
    </p>
  );
}
