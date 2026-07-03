/**
 * Splits a chunk of answer text on [n] citation markers into an ordered
 * list of plain-text and citation parts, for rendering inline citation
 * links within streamed/rendered text.
 *
 * Re-parses the FULL accumulated text on every call rather than trying to
 * track partial markers across streaming updates — this is what makes it
 * robust to token boundaries falling anywhere relative to a "[1]" marker.
 */

export type CitedTextPart =
  | { type: "text"; value: string }
  | { type: "citation"; index: number };

const CITATION_PATTERN = /\[(\d+)\]/g;

export function splitOnCitations(text: string): CitedTextPart[] {
  const parts: CitedTextPart[] = [];
  let lastIndex = 0;

  for (const match of text.matchAll(CITATION_PATTERN)) {
    const matchIndex = match.index ?? 0;
    if (matchIndex > lastIndex) {
      parts.push({ type: "text", value: text.slice(lastIndex, matchIndex) });
    }
    parts.push({ type: "citation", index: Number(match[1]) });
    lastIndex = matchIndex + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push({ type: "text", value: text.slice(lastIndex) });
  }

  return parts;
}
