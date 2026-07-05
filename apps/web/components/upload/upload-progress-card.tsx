"use client";

import { AlertCircle, CheckCircle2, Loader2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { IngestStepper } from "@/components/upload/ingest-stepper";
import type { UploadTask } from "@/components/upload/use-document-uploads";
import { getDocKindIcon } from "@/lib/file-type";

export function UploadProgressCard({
  task,
  onDismiss,
}: {
  task: UploadTask;
  onDismiss: (id: string) => void;
}) {
  const Icon = getDocKindIcon(task.file.name);
  const canDismiss = task.phase === "done" || task.phase === "error";

  return (
    <Card className="flex-row items-start gap-3 p-4">
      <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
        <Icon className="size-4 text-muted-foreground" />
      </div>

      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <p className="truncate text-sm font-medium" title={task.file.name}>
            {task.file.name}
          </p>
          {canDismiss && (
            <Button
              variant="ghost"
              size="icon"
              className="size-6 shrink-0"
              onClick={() => onDismiss(task.id)}
              aria-label={`Dismiss ${task.file.name}`}
            >
              <X className="size-3.5" />
            </Button>
          )}
        </div>

        {task.phase === "uploading" && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            Uploading&hellip;
          </div>
        )}

        {task.phase === "polling" && (
          <IngestStepper
            jobStatus={
              task.jobStatus === "failed" ? null : (task.jobStatus ?? "queued")
            }
          />
        )}

        {task.phase === "done" && (
          <div className="flex items-center gap-1.5 text-xs text-success">
            <CheckCircle2 className="size-3.5" />
            Ready to search
          </div>
        )}

        {task.phase === "error" && (
          <div className="flex items-start gap-1.5 text-xs text-destructive">
            <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
            <span>{task.error ?? "Something went wrong."}</span>
          </div>
        )}
      </div>
    </Card>
  );
}
