"use client";

import Link from "next/link";
import { ExternalLink, FileText, Hash, Layers } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { parseSourceRef } from "@/lib/parse-source-ref";
import type { RetrievedSource } from "@/lib/types";

export interface SelectedCitation {
  index: number;
  source?: RetrievedSource;
}

/**
 * Sheet showing details for one [n] citation: the source document, page,
 * and section it came from.
 *
 * NOTE ON SCOPE: the /chat SSE stream intentionally caps the "retrieve"
 * tool_result payload at the first 5 chunks (see chat.py's
 * _extract_node_data) to keep events small, and never includes the raw
 * chunk text at all. So this drawer shows what we genuinely have — doc,
 * page, section, relevance score — not a text excerpt, and citations
 * beyond index 5 show a graceful "not available" state rather than
 * fabricated content.
 */
export function CitationDrawer({
  citation,
  onOpenChange,
  docTitle,
}: {
  citation: SelectedCitation | null;
  onOpenChange: (open: boolean) => void;
  /** Resolved via a doc_id -> title lookup from the Library, if available. */
  docTitle?: string;
}) {
  const open = citation !== null;
  const parsed = citation?.source ? parseSourceRef(citation.source.source_ref) : null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md">
        <SheetHeader>
          <SheetTitle>
            Source {citation?.index !== undefined ? `[${citation.index}]` : ""}
          </SheetTitle>
          <SheetDescription>
            {citation?.source
              ? "Where this part of the answer came from."
              : "No details are available for this citation."}
          </SheetDescription>
        </SheetHeader>

        {citation?.source && parsed ? (
          <div className="flex flex-col gap-4 px-4">
            <div className="flex items-start gap-3 rounded-lg border border-border p-3">
              <div className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
                <FileText className="size-4 text-muted-foreground" />
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">
                  {docTitle ?? parsed.docId}
                </p>
                <p className="text-xs text-muted-foreground">Document</p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              {parsed.page !== null && (
                <Badge variant="outline">
                  <Layers className="size-3" />
                  Page {parsed.page}
                </Badge>
              )}
              {parsed.section && (
                <Badge variant="outline">
                  <Hash className="size-3" />
                  {parsed.section}
                </Badge>
              )}
              <Badge variant="accent">
                {Math.round(citation.source.score * 100) / 100} relevance
              </Badge>
            </div>

            <Button variant="outline" size="sm" asChild className="self-start">
              <Link href="/library">
                <ExternalLink className="size-3.5" />
                View in Library
              </Link>
            </Button>
          </div>
        ) : (
          citation && (
            <div className="px-4">
              <p className="text-sm text-muted-foreground">
                This citation refers to a source beyond the first five used
                in this answer, so its document, page, and section details
                weren&rsquo;t included in the response stream.
              </p>
            </div>
          )
        )}
      </SheetContent>
    </Sheet>
  );
}
