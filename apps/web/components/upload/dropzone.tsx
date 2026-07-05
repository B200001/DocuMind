"use client";

import * as React from "react";
import { UploadCloud } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { ACCEPTED_INPUT_ACCEPT, ACCEPTED_SUMMARY, isSupportedFile } from "@/lib/file-type";

export interface DropzoneProps {
  onFilesSelected: (files: File[]) => void;
  disabled?: boolean;
  className?: string;
}

/**
 * Drag-and-drop multi-file upload zone. Also click-to-browse via a
 * hidden native file input. Filters out unsupported file types client-side
 * before calling onFilesSelected, surfacing a toast for anything rejected.
 */
export function Dropzone({ onFilesSelected, disabled, className }: DropzoneProps) {
  const [isDragging, setIsDragging] = React.useState(false);
  const [dragDepth, setDragDepth] = React.useState(0);
  const inputRef = React.useRef<HTMLInputElement>(null);

  function handleFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;

    const files = Array.from(fileList);
    const valid: File[] = [];
    const invalidNames: string[] = [];

    for (const file of files) {
      if (isSupportedFile(file.name)) {
        valid.push(file);
      } else {
        invalidNames.push(file.name);
      }
    }

    if (invalidNames.length > 0) {
      toast.error(
        invalidNames.length === 1
          ? `Unsupported file type: ${invalidNames[0]}`
          : `${invalidNames.length} files skipped — unsupported type`,
        { description: `Accepted formats: ${ACCEPTED_SUMMARY}` }
      );
    }

    if (valid.length > 0) {
      onFilesSelected(valid);
    }
  }

  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled}
      aria-label="Upload documents"
      onClick={() => !disabled && inputRef.current?.click()}
      onKeyDown={(e) => {
        if (!disabled && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          inputRef.current?.click();
        }
      }}
      onDragOver={(e) => {
        e.preventDefault();
      }}
      onDragEnter={(e) => {
        e.preventDefault();
        if (disabled) return;
        setDragDepth((d) => d + 1);
        setIsDragging(true);
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        setDragDepth((d) => {
          const next = d - 1;
          if (next <= 0) setIsDragging(false);
          return next;
        });
      }}
      onDrop={(e) => {
        e.preventDefault();
        setIsDragging(false);
        setDragDepth(0);
        if (disabled) return;
        handleFiles(e.dataTransfer.files);
      }}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors",
        isDragging
          ? "border-primary bg-primary/5"
          : "border-border hover:border-muted-foreground/40 hover:bg-muted/30",
        disabled && "pointer-events-none opacity-60",
        className
      )}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED_INPUT_ACCEPT}
        className="hidden"
        disabled={disabled}
        onChange={(e) => {
          handleFiles(e.target.files);
          e.target.value = "";
        }}
      />

      <div
        className={cn(
          "flex size-12 items-center justify-center rounded-full transition-colors",
          isDragging ? "bg-primary/15" : "bg-muted"
        )}
      >
        <UploadCloud
          className={cn("size-5", isDragging ? "text-primary" : "text-muted-foreground")}
        />
      </div>

      <div className="space-y-1">
        <p className="text-sm font-medium">
          {isDragging ? "Drop to upload" : "Drag and drop files, or click to browse"}
        </p>
        <p className="text-xs text-muted-foreground">{ACCEPTED_SUMMARY}</p>
      </div>
    </div>
  );
}
