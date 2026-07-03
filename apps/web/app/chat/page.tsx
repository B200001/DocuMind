"use client";

import * as React from "react";

import { ChatInput } from "@/components/chat/chat-input";
import { MessageThread } from "@/components/chat/message-thread";
import { useChat } from "@/components/chat/use-chat";
import { listDocuments } from "@/lib/api";

export default function ChatPage() {
  const { messages, isPending, sendMessage, stop } = useChat();

  // doc_id -> title, so citation cards can show a friendly document name
  // instead of the raw hash-like doc_id. Best-effort: if this fetch fails
  // the drawer just falls back to showing the doc_id itself.
  const [docTitles, setDocTitles] = React.useState<Record<string, string>>({});

  React.useEffect(() => {
    listDocuments()
      .then((docs) => {
        setDocTitles(Object.fromEntries(docs.map((d) => [d.doc_id, d.title])));
      })
      .catch(() => {
        // Non-critical — citation drawer degrades to showing doc_id.
      });
  }, []);

  return (
    <div className="flex h-[calc(100dvh-4rem)] flex-col md:h-[calc(100dvh-2rem)]">
      <MessageThread messages={messages} onRetry={sendMessage} docTitles={docTitles} />
      <ChatInput onSend={sendMessage} onStop={stop} isPending={isPending} />
    </div>
  );
}
