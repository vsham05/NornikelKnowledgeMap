import type { Locale } from "@/lib/i18n/translations";
import { translate } from "@/lib/i18n/translations";

/** Process-material taxonomy — mirrors backend ontology.yaml material_classes */

export interface MaterialClassOption {
  id: string;
  label: string;
  stage: string;
  hint?: string;
}

export const MATERIAL_CLASS_OPTIONS: MaterialClassOption[] = [
  { id: "ore", label: "Ore & ROM", stage: "feedstock", hint: "Run-of-mine, crude ore" },
  { id: "mineral", label: "Mineral", stage: "feedstock", hint: "Ore minerals, gangue" },
  { id: "concentrate", label: "Concentrate", stage: "beneficiation", hint: "Flotation/gravity concentrate" },
  { id: "intermediate", label: "Intermediate", stage: "processing", hint: "Matte, slag, cathode, precipitate" },
  { id: "metal", label: "Metal", stage: "product", hint: "Elemental metals" },
  { id: "alloy", label: "Alloy & steel", stage: "engineering", hint: "Stainless, specialty alloys" },
  { id: "solution", label: "Process fluid", stage: "processing", hint: "Electrolyte, leachate, liquor" },
  { id: "reagent", label: "Reagent", stage: "processing", hint: "Acids, collectors, flux" },
  { id: "compound", label: "Compound", stage: "processing", hint: "Salts, carbonates, sulfates" },
  { id: "composite", label: "Composite", stage: "engineering", hint: "Clad, multi-phase" },
  { id: "ceramic", label: "Ceramic", stage: "engineering", hint: "Refractories" },
  { id: "polymer", label: "Polymer", stage: "engineering", hint: "Liners, coatings" },
];

export function materialClassLabel(id: string | undefined, locale?: Locale): string {
  if (!id) return "";
  if (locale) {
    const key = `materialClass.${id}`;
    const translated = translate(locale, key);
    if (translated !== key) return translated;
  }
  return MATERIAL_CLASS_OPTIONS.find((o) => o.id === id)?.label ?? id;
}
