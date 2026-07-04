/** Human-readable formatting for property / composition values from the graph. */

export interface ParsedComposition {
  kind: "composition" | "scalar" | "range" | "threshold";
  display: string;
  elements?: Array<{ symbol: string; value: string; unit?: string }>;
  unit?: string;
}

function tryParseDictString(raw: string): Record<string, unknown> | null {
  const trimmed = raw.trim();
  if (!trimmed.startsWith("{") || !trimmed.endsWith("}")) return null;
  try {
    const jsonish = trimmed.replace(/'/g, '"');
    const parsed = JSON.parse(jsonish) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    /* fall through */
  }
  return null;
}

export function parsePropertyValue(
  value: string,
  unit?: string
): ParsedComposition {
  const raw = (value ?? "").trim();
  if (!raw) {
    return { kind: "scalar", display: "—" };
  }

  const dict = tryParseDictString(raw);
  if (dict && Object.keys(dict).length > 0) {
    const elements = Object.entries(dict).map(([symbol, val]) => ({
      symbol,
      value: String(val).replace(/^<\s*/, "<").trim(),
      unit: unit?.trim() || undefined,
    }));
    const preview = elements
      .slice(0, 4)
      .map((e) => `${e.symbol} ${e.value}${e.unit ? ` ${e.unit}` : ""}`)
      .join(" · ");
    const suffix = elements.length > 4 ? ` +${elements.length - 4}` : "";
    return {
      kind: "composition",
      display: preview + suffix,
      elements,
      unit: unit?.trim() || undefined,
    };
  }

  if (/^<\s*[\d.,]+/.test(raw)) {
    return {
      kind: "threshold",
      display: raw,
      unit: unit?.trim() || undefined,
    };
  }

  if (/[\d.,]+\s*[-–—]\s*[\d.,]+/.test(raw)) {
    return {
      kind: "range",
      display: raw,
      unit: unit?.trim() || undefined,
    };
  }

  return {
    kind: "scalar",
    display: raw,
    unit: unit?.trim() || undefined,
  };
}

export function measurementKey(
  materialName?: string,
  experimentName?: string,
  value?: string
): string {
  return `${materialName ?? ""}|${experimentName ?? ""}|${value ?? ""}`.toLowerCase();
}
