"use client";

import * as React from "react";

import { Separator } from "@/components/ui/separator";
import { Dropzone } from "@/components/upload/dropzone";
import { UploadProgressList } from "@/components/upload/upload-progress-list";
import { useDocumentUploads } from "@/components/upload/use-document-uploads";
import { DocumentGrid } from "@/components/documents/document-grid";
import { ApiError, listDocuments } from "@/lib/api";
import type { Document } from "@/lib/types";

export default function LibraryPage() {
  const [documents, setDocuments] = React.useState<Document[] | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    setError(null);
    try {
      const docs = await listDocuments();
      setDocuments(docs);
    } catch (err) {
      setDocuments(null);
      setError(
        err instanceof ApiError ? err.message : "Something went wrong loading documents."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const { tasks, startUpload, dismissTask } = useDocumentUploads(() => {
    refresh();
  });

  const handleDeleted = React.useCallback((docId: string) => {
    setDocuments((prev) => prev?.filter((d) => d.doc_id !== docId) ?? prev);
  }, []);

  const isUploading = tasks.some(
    (t) => t.phase === "uploading" || t.phase === "polling"
  );
  const readyCount = documents?.filter((d) => d.status === "ready").length ?? 0;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-display text-2xl font-medium tracking-tight">Library</h1>
        <p className="text-sm text-muted-foreground">
          {readyCount > 0
            ? `${readyCount} ${readyCount === 1 ? "document" : "documents"} ready to search in Chat.`
            : "Upload documents to make them searchable in Chat."}
        </p>
      </div>

      <Dropzone
        onFilesSelected={(files) => files.forEach(startUpload)}
        disabled={isUploading && tasks.length >= 8}
      />

      <UploadProgressList tasks={tasks} onDismiss={dismissTask} />

      <Separator />

      <DocumentGrid
        documents={documents}
        loading={loading}
        error={error}
        onRetry={() => {
          setLoading(true);
          refresh();
        }}
        onDeleted={handleDeleted}
      />
    </div>
  );
}
