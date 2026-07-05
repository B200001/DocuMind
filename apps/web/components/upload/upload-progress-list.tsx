"use client";

import { UploadProgressCard } from "@/components/upload/upload-progress-card";
import type { UploadTask } from "@/components/upload/use-document-uploads";

export function UploadProgressList({
  tasks,
  onDismiss,
}: {
  tasks: UploadTask[];
  onDismiss: (id: string) => void;
}) {
  if (tasks.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {tasks.map((task) => (
        <UploadProgressCard key={task.id} task={task} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
