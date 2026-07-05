"use client";

import * as React from "react";
import { Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ApiError, deleteDocument } from "@/lib/api";
import type { Document } from "@/lib/types";

export function DocumentDeleteDialog({
  document,
  open,
  onOpenChange,
  onDeleted,
}: {
  document: Document;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted: (docId: string) => void;
}) {
  const [isDeleting, setIsDeleting] = React.useState(false);

  async function handleConfirm() {
    setIsDeleting(true);
    try {
      await deleteDocument(document.doc_id);
      toast.success(`"${document.title}" deleted`);
      onDeleted(document.doc_id);
      onOpenChange(false);
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Failed to delete the document.";
      toast.error("Delete failed", { description: message });
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !isDeleting && onOpenChange(next)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete this document?</DialogTitle>
          <DialogDescription>
            <span className="font-medium text-foreground">&ldquo;{document.title}&rdquo;</span>{" "}
            and all of its indexed content will be permanently removed. This
            can&rsquo;t be undone, and it will no longer be searchable in Chat.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isDeleting}
          >
            Cancel
          </Button>
          <Button variant="destructive" onClick={handleConfirm} disabled={isDeleting}>
            {isDeleting ? (
              <>
                <Loader2 className="animate-spin" />
                Deleting&hellip;
              </>
            ) : (
              <>
                <Trash2 />
                Delete
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
