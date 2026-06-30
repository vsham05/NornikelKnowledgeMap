import type { ParsedQuery } from "./types";

const STOP_WORDS = new Set([
  "what", "has", "been", "done", "on", "under", "and", "the", "for",
  "was", "were", "effect", "how", "does", "affect", "with", "in",
  "of", "to", "is", "are", "already", "about", "show", "me", "find",
  "give", "good", "main", "points", "from", "your", "that", "this",
]);

export function parseQuery(query: string): ParsedQuery {
  const lower = query.toLowerCase();
  const keywords = lower
    .replace(/[^a-z0-9\s-]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length > 2 && !STOP_WORDS.has(w));

  return { keywords };
}
