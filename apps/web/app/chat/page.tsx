import { Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";

export default function ChatPage() {
  return (
    <div className="flex h-[calc(100dvh-4rem)] flex-col md:h-[calc(100dvh-2rem)]">
      <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
        <Badge variant="accent" className="mb-1">
          Grounded answers
        </Badge>
        <h1 className="font-display text-2xl font-medium tracking-tight">
          Ask your documents anything
        </h1>
        <p className="max-w-sm text-sm text-muted-foreground">
          Every answer cites the exact passages it came from — no
          hallucinated sources.
        </p>
      </div>

      <div className="sticky bottom-0 flex items-end gap-2 border-t border-border bg-background pt-4">
        <Textarea
          placeholder="What is the refund policy?"
          className="min-h-11 resize-none"
          rows={1}
        />
        <Button size="icon" aria-label="Send">
          <Send className="size-4" />
        </Button>
      </div>
    </div>
  );
}
