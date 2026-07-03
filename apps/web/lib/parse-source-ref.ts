/**
 * Parses a source_ref string produced by hybrid.py's _make_source_ref():
 *
 *   "<doc_id>"                      -> { docId, page: null,    section: null }
 *   "<doc_id> p.<N>"                -> { docId, page: N,       section: null }
 *   "<doc_id> § <section>"          -> { docId, page: null,    section }
 *   "<doc_id> p.<N> § <section>"    -> { docId, page: N,       section }
 *
 * doc_id is always a single token with no spaces (it's a hex hash — see
 * documind_core.ingestion.pipeline._doc_id_for_path), so splitting on the
 * first space-delimited token is safe.
 */

export interface ParsedSourceRef {
  docId: string;
  page: number | null;
  section: string | null;
}

const SOURCE_REF_PATTERN = /^(\S+)(?: p\.(\d+))?(?: § (.+))?$/;

export function parseSourceRef(ref: string): ParsedSourceRef {
  const match = ref.match(SOURCE_REF_PATTERN);
  if (!match) {
    return { docId: ref, page: null, section: null };
  }
  const [, docId, page, section] = match;
  return {
    docId,
    page: page ? Number(page) : null,
    section: section ?? null,
  };
}
