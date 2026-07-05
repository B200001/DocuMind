"use client";

import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import { ApiError, pollDocumentStatus, uploadDocument } from "@/lib/api";
import type { JobStatus } from "@/lib/types";

export type UploadPhase = "uploading" | "polling" | "done" | "error";

export interface UploadTask {
  id: string;
  file: File;
  docId?: string;
  jobStatus: JobStatus | null;
  phase: UploadPhase;
  error?: string;
}

/**
 * Orchestrates one or more concurrent file uploads: POSTs each file,
 * then polls its ingestion status until it reaches a terminal state.
 *
 * Each upload runs independently (multiple files upload and poll in
 * parallel, not sequentially) so a slow document doesn't block others.
 *
 * @param onDocumentReady - Called with the doc_id once a document finishes
 *   ingesting successfully. Typically used to refresh the document list.
 */
export function useDocumentUploads(onDocumentReady: (docId: string) => void) {
  const [tasks, setTasks] = useState<UploadTask[]>([]);
  const controllers = useRef<Map<string, AbortController>>(new Map());

  const updateTask = useCallback((id: string, patch: Partial<UploadTask>) => {
    setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)));
  }, []);

  const startUpload = useCallback(
    (file: File) => {
      const id = crypto.randomUUID();
      const controller = new AbortController();
      controllers.current.set(id, controller);

      setTasks((prev) => [
        ...prev,
        { id, file, jobStatus: null, phase: "uploading" as const },
      ]);

      (async () => {
        try {
          const { doc_id } = await uploadDocument(file);
          updateTask(id, { docId: doc_id, phase: "polling", jobStatus: "queued" });

          const final = await pollDocumentStatus(doc_id, {
            signal: controller.signal,
            onUpdate: (status) => updateTask(id, { jobStatus: status.status }),
          });

          if (final.status === "completed") {
            updateTask(id, { phase: "done", jobStatus: "completed" });
            toast.success(`${file.name} is ready`, {
              description: "You can now ask questions about it in Chat.",
            });
            onDocumentReady(doc_id);
          } else {
            const message = final.error ?? "Ingestion failed for an unknown reason.";
            updateTask(id, { phase: "error", jobStatus: "failed", error: message });
            toast.error(`${file.name} failed to process`, { description: message });
          }
        } catch (err) {
          if (err instanceof Error && err.message === "Polling aborted.") {
            return;
          }
          const message =
            err instanceof ApiError
              ? err.message
              : err instanceof Error
                ? err.message
                : "Upload failed unexpectedly.";
          updateTask(id, { phase: "error", error: message });
          toast.error(`${file.name} failed to upload`, { description: message });
        } finally {
          controllers.current.delete(id);
        }
      })();

      return id;
    },
    [onDocumentReady, updateTask]
  );

  /** Remove a task from the list. Aborts in-flight polling if it's still running. */
  const dismissTask = useCallback((id: string) => {
    controllers.current.get(id)?.abort();
    controllers.current.delete(id);
    setTasks((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return { tasks, startUpload, dismissTask };
}
