import { Badge } from "@/components/ui/badge";
import { UserMessage } from "@/components/chat/user-message";
import { AssistantMessage } from "@/components/chat/assistant-message";
import type { ChatMessage } from "@/components/chat/types";

export function MessageThread({
  messages,
  onRetry,
  docTitles,
}: {
  messages: ChatMessage[];
  onRetry: (query: string) => void;
  docTitles?: Record<string, string>;
}) {
  if (messages.length === 0) {
    return (
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
    );
  }

  return (
    <div className="flex flex-1 flex-col gap-6 py-4">
      {messages.map((message) =>
        message.role === "user" ? (
          <UserMessage key={message.id} content={message.content} />
        ) : (
          <AssistantMessage
            key={message.id}
            message={message}
            onRetry={onRetry}
            docTitles={docTitles}
          />
        )
      )}
    </div>
  );
}
