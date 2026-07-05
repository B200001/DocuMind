"use client";

import * as React from "react";
import { Calendar, Hash, Layers, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { DocumentDeleteDialog } from "@/components/documents/document-delete-dialog";
import { DocumentStatusBadge } from "@/components/documents/document-status-badge";
import { getDocKindIcon, getDocKindLabel } from "@/lib/file-type";
import type { Document } from "@/lib/types";

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  year: "numeric",
});

export function DocumentCard({
  document,
  onDeleted,
}: {
  document: Document;
  onDeleted: (docId: string) => void;
}) {
  const [confirmOpen, setConfirmOpen] = React.useState(false);

  const Icon = getDocKindIcon(document.source_path);
  const kindLabel = getDocKindLabel(document.source_path);

  return (
    <>
      <Card className="gap-4 py-4">
        <CardContent className="flex flex-col gap-3 px-4">
          <div className="flex items-start justify-between gap-2">
            <div className="flex min-w-0 items-start gap-2.5">
              <div className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
                <Icon className="size-4 text-muted-foreground" />
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium" title={document.title}>
                  {document.title}
                </p>
                <p className="text-xs text-muted-foreground">{kindLabel}</p>
              </div>
            </div>

            <Button
              variant="ghost"
              size="icon"
              className="size-7 shrink-0 text-muted-foreground hover:text-destructive"
              onClick={() => setConfirmOpen(true)}
              aria-label={`Delete ${document.title}`}
            >
              <Trash2 className="size-3.5" />
            </Button>
          </div>

          <DocumentStatusBadge status={document.status} />

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {document.page_count !== null && (
              <span className="flex items-center gap-1">
                <Layers className="size-3" />
                {document.page_count} {document.page_count === 1 ? "page" : "pages"}
              </span>
            )}
            {document.chunk_count !== null && (
              <span className="flex items-center gap-1">
                <Hash className="size-3" />
                {document.chunk_count} {document.chunk_count === 1 ? "chunk" : "chunks"}
              </span>
            )}
            <span className="flex items-center gap-1">
              <Calendar className="size-3" />
              {dateFormatter.format(new Date(document.created_at))}
            </span>
          </div>
        </CardContent>
      </Card>

      <DocumentDeleteDialog
        document={document}
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        onDeleted={onDeleted}
      />
    </>
  );
}
