"use client";

import * as React from "react";
import { Send, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export function ChatInput({
  onSend,
  onStop,
  isPending,
}: {
  onSend: (query: string) => void;
  onStop: () => void;
  isPending: boolean;
}) {
  const [value, setValue] = React.useState("");

  function handleSubmit() {
    const trimmed = value.trim();
    if (!trimmed || isPending) return;
    onSend(trimmed);
    setValue("");
  }

  return (
    <div className="sticky bottom-0 flex items-end gap-2 border-t border-border bg-background pt-4">
      <Textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
          }
        }}
        placeholder={
          isPending ? "Waiting for a response\u2026" : "Ask a question about your documents\u2026"
        }
        disabled={isPending}
        className="min-h-11 resize-none"
        rows={1}
      />
      {isPending ? (
        <Button size="icon" variant="outline" onClick={onStop} aria-label="Stop generating">
          <Square className="size-3.5" />
        </Button>
      ) : (
        <Button
          size="icon"
          onClick={handleSubmit}
          disabled={!value.trim()}
          aria-label="Send"
        >
          <Send className="size-4" />
        </Button>
      )}
    </div>
  );
}
