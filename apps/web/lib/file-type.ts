/**
 * Client-side knowledge of which file types the ingestion pipeline accepts.
 *
 * Mirrors _EXT_MAP in packages/documind_core/documind_core/loaders/registry.py —
 * keep the two in sync by hand when a new loader is added.
 */

import { FileCode, FileText, FileType, Globe, type LucideIcon } from "lucide-react";

interface DocKind {
  label: string;
  icon: LucideIcon;
}

const KIND_BY_EXTENSION: Record<string, DocKind> = {
  ".pdf": { label: "PDF", icon: FileText },
  ".docx": { label: "Word document", icon: FileType },
  ".doc": { label: "Word document", icon: FileType },
  ".html": { label: "HTML page", icon: Globe },
  ".htm": { label: "HTML page", icon: Globe },
  ".md": { label: "Markdown", icon: FileCode },
  ".markdown": { label: "Markdown", icon: FileCode },
  ".txt": { label: "Plain text", icon: FileText },
};

export const ACCEPTED_EXTENSIONS = Object.keys(KIND_BY_EXTENSION);

/** Value for the native file input's `accept` attribute. */
export const ACCEPTED_INPUT_ACCEPT = ACCEPTED_EXTENSIONS.join(",");

/** Human-readable list for empty states and rejection toasts. */
export const ACCEPTED_SUMMARY = "PDF, DOCX, HTML, Markdown, or plain text";

function extensionOf(fileName: string): string {
  const dot = fileName.lastIndexOf(".");
  return dot === -1 ? "" : fileName.slice(dot).toLowerCase();
}

export function isSupportedFile(fileName: string): boolean {
  return extensionOf(fileName) in KIND_BY_EXTENSION;
}

const FALLBACK_KIND: DocKind = { label: "Document", icon: FileText };

export function getDocKindIcon(pathOrName: string): LucideIcon {
  return (KIND_BY_EXTENSION[extensionOf(pathOrName)] ?? FALLBACK_KIND).icon;
}

export function getDocKindLabel(pathOrName: string): string {
  return (KIND_BY_EXTENSION[extensionOf(pathOrName)] ?? FALLBACK_KIND).label;
}
