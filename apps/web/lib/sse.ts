/**
 * SSE client for POST /chat.
 *
 * EventSource is GET-only, so we use fetch + ReadableStream and parse the
 * text/event-stream format by hand. The backend emits one JSON payload per
 * event as `data: {...}\n\n` (see apps/api/app/sse.py).
 *
 * Parser notes:
 * - Events are delimited by a BLANK line (`\n\n`); splitting on single
 *   newlines would tear events in half.
 * - decode(value, { stream: true }) is required so multi-byte UTF-8
 *   characters split across network chunks reassemble correctly.
 * - Per the SSE spec, an event may carry several `data:` lines that join
 *   with "\n"; comment lines (starting with ":") and other fields are
 *   ignored.
 */

import { API_URL } from "@/lib/api";
import type { ChatEvent, ChatRequest } from "@/lib/types";

/** Connection-level failure: server unreachable, HTTP error, or empty body. */
export class ChatStreamError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ChatStreamError";
    this.status = status;
  }
}

/** Extract the joined data payload from one raw SSE event block, or null. */
function parseEventBlock(block: string): string | null {
  const dataLines: string[] = [];
  for (const rawLine of block.split(/\r?\n/)) {
    if (rawLine.startsWith("data:")) {
      // Spec: a single leading space after the colon is stripped.
      dataLines.push(rawLine.slice(5).replace(/^ /, ""));
    }
    // Ignore comments (":...") and fields like "event:"/"id:" — the
    // backend encodes the event type inside the JSON payload itself.
  }
  if (dataLines.length === 0) return null;
  return dataLines.join("\n");
}

/**
 * POST the query to /chat and yield each streamed ChatEvent as it arrives.
 *
 * Aborting the signal rejects the in-flight read with a DOMException
 * ("AbortError"), which callers treat as "user pressed stop", not an error.
 *
 * @example
 *   for await (const event of streamChat("what is the refund window?")) {
 *     if (event.type === "token") append(event.text);
 *   }
 */
export async function* streamChat(
  query: string,
  { signal }: { signal?: AbortSignal } = {}
): AsyncGenerator<ChatEvent, void, undefined> {
  const body: ChatRequest = { query };

  let response: Response;
  try {
    response = await fetch(`${API_URL}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(body),
      signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ChatStreamError(
      0,
      `Could not reach the API at ${API_URL}. Is the backend running?`
    );
  }

  if (!response.ok) {
    let detail = `The chat request failed with HTTP ${response.status}.`;
    try {
      const errBody = await response.json();
      if (typeof errBody?.detail === "string") detail = errBody.detail;
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new ChatStreamError(response.status, detail);
  }

  if (!response.body) {
    throw new ChatStreamError(0, "The server returned an empty response stream.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Drain every complete event currently in the buffer.
      let separatorIndex: number;
      while ((separatorIndex = buffer.search(/\r?\n\r?\n/)) !== -1) {
        const separatorLength = buffer[separatorIndex] === "\r" ? 4 : 2;
        const block = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + separatorLength);

        const data = parseEventBlock(block);
        if (data === null) continue;

        let event: ChatEvent;
        try {
          event = JSON.parse(data) as ChatEvent;
        } catch {
          continue; // Malformed frame — skip rather than kill the stream.
        }
        yield event;
      }
    }

    // Flush a final event that arrived without a trailing blank line.
    const data = parseEventBlock(buffer);
    if (data !== null) {
      try {
        yield JSON.parse(data) as ChatEvent;
      } catch {
        // Trailing partial frame — nothing usable.
      }
    }
  } finally {
    // Ensure the HTTP connection is released if the consumer breaks early.
    reader.cancel().catch(() => {});
  }
}
