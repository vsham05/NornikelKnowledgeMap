import type { ParsedQuery, StructuredFilters } from "./types";
import { MATERIAL_TERMS, PROCESS_TERMS, PROPERTY_TERMS } from "./miningTerms";

const STOP_WORDS = new Set([
  "what", "has", "been", "done", "on", "under", "and", "the", "for",
  "was", "were", "effect", "how", "does", "affect", "with", "in",
  "of", "to", "is", "are", "already", "about", "show", "me", "find",
  "give", "good", "main", "points", "from", "your", "that", "this",
  "какие", "какой", "какая", "что", "где", "при", "для", "или", "все",
]);

function matchTerm(text: string, terms: string[]): string | undefined {
  const lower = text.toLowerCase();
  const hit = terms.find((t) => lower.includes(t.toLowerCase()));
  return hit;
}

export function parseQuery(query: string): ParsedQuery {
  const lower = query.toLowerCase();
  const keywords = lower
    .replace(/[^a-z0-9а-яё\s-]/gi, " ")
    .split(/\s+/)
    .filter((w) => w.length > 2 && !STOP_WORDS.has(w));

  let geography: string | undefined;
  if (/росси|domestic|отечеств|cis/i.test(query)) geography = "domestic";
  else if (/international|global|зарубеж|миров/i.test(query)) geography = "international";

  return {
    material: matchTerm(query, MATERIAL_TERMS),
    mode: matchTerm(query, PROCESS_TERMS),
    property: matchTerm(query, PROPERTY_TERMS),
    geography,
    keywords,
  };
}

export function parsedToStructured(parsed: ParsedQuery): StructuredFilters {
  return {
    material: parsed.material,
    process: parsed.mode,
    geography: parsed.geography,
    propertyName: parsed.property,
  };
}

export function structuredToBackend(sf: StructuredFilters) {
  return {
    material: sf.material,
    material_class: sf.materialClass,
    process: sf.process,
    geography: sf.geography,
    year_from: sf.yearFrom,
    year_to: sf.yearTo,
    property_name: sf.propertyName,
    value_min: sf.valueMin,
    value_max: sf.valueMax,
  };
}
