/** Split pipe/comma-separated material labels from LLM or graph nodes. */
export function splitCompoundName(name: string): string[] {
  if (!name?.trim()) return [];
  return name
    .split(/[|/,;]+/)
    .map((part) => part.trim().replace(/\.{2,}$/, ""))
    .filter((part) => part.length > 0);
}

/** Taxonomy category labels — not real material names. */
const GENERIC_CLASS_LABELS = new Set([
  "ore",
  "mineral",
  "concentrate",
  "intermediate",
  "metal",
  "alloy",
  "solution",
  "reagent",
  "compound",
  "composite",
  "ceramic",
  "polymer",
  "other",
  "feed",
  "feedstock",
  "product",
  "engineering",
  "processing",
  "beneficiation",
  "solid",
  "liquid",
  "powder",
  "film",
  "substance",
  "material",
]);

export function isGenericClassLabel(name: string): boolean {
  const cleaned = name.trim().toLowerCase();
  if (!cleaned) return true;

  if (/[|;,/]/.test(cleaned)) {
    const parts = splitCompoundName(cleaned);
    return parts.length > 0 && parts.every((part) => isGenericClassLabel(part));
  }

  if (GENERIC_CLASS_LABELS.has(cleaned)) return true;

  const tokens = cleaned.split(/[\s_\-]+/).filter(Boolean);
  if (tokens.length <= 1) return false;

  return tokens.every((t) => GENERIC_CLASS_LABELS.has(t));
}

export function parseMaterialComponents(
  name: string,
  aliases: string[] = []
): string[] {
  const seen = new Set<string>();
  const out: string[] = [];

  const add = (value: string) => {
    if (isGenericClassLabel(value)) return;
    const key = value.toLowerCase();
    if (!key || seen.has(key)) return;
    seen.add(key);
    out.push(value);
  };

  for (const part of splitCompoundName(name)) add(part);
  if (out.length === 0 && name.trim() && !isGenericClassLabel(name)) {
    add(name.trim());
  }

  for (const alias of aliases) {
    for (const part of splitCompoundName(alias)) add(part);
  }

  return out;
}

/** Short label for a merged material blob on the graph. */
export function mergedMaterialLabel(components: string[]): string {
  if (components.length === 0) return "Materials";
  if (components.length === 1) return components[0];
  if (components.length <= 3) return components.join(" · ");
  return `${components.slice(0, 2).join(" · ")} +${components.length - 2}`;
}
