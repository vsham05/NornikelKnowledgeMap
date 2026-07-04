/** Stable canonical keys for graph entity deduplication (mirrors backend glossary). */

const GLOSSARY: Record<string, string> = {
  nickel: "nickel",
  никель: "nickel",
  copper: "copper",
  медь: "copper",
  cobalt: "cobalt",
  кобальт: "cobalt",
  iron: "iron",
  железо: "iron",
  zinc: "zinc",
  цинк: "zinc",
  magnesium: "magnesium",
  магний: "magnesium",
  manganese: "manganese",
  марганец: "manganese",
  aluminum: "aluminum",
  алюминий: "aluminum",
  gold: "gold",
  золото: "gold",
  silver: "silver",
  серебро: "silver",
  platinum: "platinum",
  платина: "platinum",
  palladium: "palladium",
  палладий: "palladium",
  sulfur: "sulfur",
  сера: "sulfur",
  gypsum: "gypsum",
  гипс: "gypsum",
  limonite: "limonite",
  лимонит: "limonite",
  matte: "matte",
  матт: "matte",
  slag: "slag",
  шлак: "slag",
  concentrate: "concentrate",
  концентрат: "concentrate",
  ore: "ore",
  руда: "ore",
  "hydrochloric acid": "hydrochloric_acid",
  "соляная кислота": "hydrochloric_acid",
  hcl: "hydrochloric_acid",
  "sulfuric acid": "sulfuric_acid",
  "серная кислота": "sulfuric_acid",
  h2so4: "sulfuric_acid",
  beneficiation: "beneficiation",
  обогащение: "beneficiation",
  flotation: "flotation",
  флотация: "flotation",
  leaching: "leaching",
  выщелачивание: "leaching",
  "heap leaching": "heap_leaching",
  "кучное выщелачивание": "heap_leaching",
  hpal: "hpal",
  hydrometallurgy: "hydrometallurgy",
  гидрометаллургия: "hydrometallurgy",
  pyrometallurgy: "pyrometallurgy",
  пирометаллургия: "pyrometallurgy",
  roasting: "roasting",
  обжиг: "roasting",
  smelting: "smelting",
  плавка: "smelting",
  refining: "refining",
  рафинирование: "refining",
  electrowinning: "electrowinning",
  электроосаждение: "electrowinning",
  precipitation: "precipitation",
  осаждение: "precipitation",
  oxidation: "oxidation",
  окисление: "oxidation",
  "magnesium chloride": "magnesium_chloride",
  "хлорид магния": "magnesium_chloride",
  "nickel laterite ore": "nickel_laterite_ore",
  "nickel laterite": "nickel_laterite_ore",
  "limonite ore": "limonite_ore",
  "лимонитовая руда": "limonite_ore",
  reactor: "reactor",
  реактор: "reactor",
  filter: "filter",
  фильтр: "filter",
  thickener: "thickener",
  сгуститель: "thickener",
  condenser: "condenser",
  конденсатор: "condenser",
  preheater: "preheater",
  подогреватель: "preheater",
  "heat exchanger": "heat_exchanger",
  "теплообменник": "heat_exchanger",
  "mixing tank": "mixing_tank",
  "mixing tanks": "mixing_tank",
  "mixers settler": "mixer_settler",
  "mixer settler": "mixer_settler",
  "bpc mixers settlers": "mixer_settler",
  "yield strength": "yield_strength",
  "предел прочности": "yield_strength",
  composition: "composition",
  состав: "composition",
};

function normalizeToken(text: string): string {
  return text
    .normalize("NFKC")
    .toLowerCase()
    .replace(/ё/g, "е")
    .replace(/[_\-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Strip trailing numeric measurement from property display labels. */
export function propertyBaseLabel(name: string): string {
  return name.replace(/:\s*[-+]?[\d.,]+.*$/i, "").trim();
}

export function canonicalEntityKey(name: string): string {
  const norm = normalizeToken(name);
  if (!norm) return "";
  if (GLOSSARY[norm]) return GLOSSARY[norm];

  const compact = norm.replace(/[^\p{L}\p{N}\s]/gu, "").replace(/\s+/g, " ").trim();
  if (GLOSSARY[compact]) return GLOSSARY[compact];

  return compact.replace(/\s+/g, "_");
}

/** Order-independent token key for equipment/process name variants. */
export function tokenSortKey(name: string): string {
  const norm = normalizeToken(name).replace(/[^\p{L}\p{N}\s]/gu, " ");
  const tokens = norm.split(/\s+/).filter((t) => t.length > 1);
  if (tokens.length === 0) return norm.replace(/\s+/g, "_");
  return tokens.sort().join("_");
}

export function pluralTokenKey(name: string): string {
  const sorted = tokenSortKey(name);
  return sorted
    .split("_")
    .map((t) => (t.length > 3 && t.endsWith("s") ? t.slice(0, -1) : t))
    .join("_");
}
