"""Ontology-driven material classification for mining/metallurgy process streams."""

from __future__ import annotations

import re
from functools import lru_cache

from domain.enums import MaterialClass, MaterialProcessStage, MaterialState
from domain.ontology import MaterialClassSchema, get_ontology

_CLASS_PRIORITY: dict[MaterialClass, int] = {
    MaterialClass.OTHER: 0,
    MaterialClass.MINERAL: 1,
    MaterialClass.ORE: 2,
    MaterialClass.CONCENTRATE: 3,
    MaterialClass.INTERMEDIATE: 4,
    MaterialClass.COMPOUND: 5,
    MaterialClass.REAGENT: 6,
    MaterialClass.SOLUTION: 7,
    MaterialClass.METAL: 8,
    MaterialClass.ALLOY: 9,
    MaterialClass.COMPOSITE: 10,
    MaterialClass.CERAMIC: 11,
    MaterialClass.POLYMER: 12,
}

# Taxonomy category labels — valid in material_class, NOT as material names.
_GENERIC_CLASS_LABELS = frozenset({
    "ore", "mineral", "concentrate", "intermediate", "metal", "alloy",
    "solution", "reagent", "compound", "composite", "ceramic", "polymer",
    "other", "feed", "feedstock", "product", "engineering", "processing",
    "beneficiation", "feedstock", "solid", "liquid", "powder", "film",
    "substance", "material", "feed concentrate", "flotation concentrate",
})

_LEGACY_ALIASES: dict[str, MaterialClass] = {
    "liquid": MaterialClass.SOLUTION,
    "stainless_steel": MaterialClass.ALLOY,
    "stainless": MaterialClass.ALLOY,
    "steel": MaterialClass.ALLOY,
    "process": MaterialClass.OTHER,
    "feed": MaterialClass.CONCENTRATE,
    "tailings": MaterialClass.INTERMEDIATE,
    "matte": MaterialClass.INTERMEDIATE,
    "slag": MaterialClass.INTERMEDIATE,
    "electrolyte": MaterialClass.SOLUTION,
    "leachate": MaterialClass.SOLUTION,
    "liquor": MaterialClass.SOLUTION,
    "catholyte": MaterialClass.SOLUTION,
    "anolyte": MaterialClass.SOLUTION,
    "precipitate": MaterialClass.INTERMEDIATE,
    "salt": MaterialClass.COMPOUND,
    "carbonate": MaterialClass.COMPOUND,
    "sulfate": MaterialClass.COMPOUND,
    "sulphate": MaterialClass.COMPOUND,
    "refractory": MaterialClass.CERAMIC,
    "ptfe": MaterialClass.POLYMER,
    "teflon": MaterialClass.POLYMER,
}


class MaterialTaxonomy:
    """Classify materials by process-stream position using ontology.yaml."""

    def __init__(self) -> None:
        self._ontology = get_ontology()
        self._alias_to_class: dict[str, MaterialClass] = {}
        self._build_alias_index()

    def _build_alias_index(self) -> None:
        for class_id, schema in self._ontology.material_classes.items():
            try:
                cls = MaterialClass(class_id)
            except ValueError:
                continue
            self._alias_to_class[class_id] = cls
            self._alias_to_class[class_id.replace("_", " ")] = cls
            for alias in schema.aliases:
                self._alias_to_class[alias.lower().strip()] = cls
        for alias, cls in _LEGACY_ALIASES.items():
            self._alias_to_class.setdefault(alias, cls)

    def get_schema(self, material_class: MaterialClass) -> MaterialClassSchema | None:
        return self._ontology.get_material_class_schema(material_class.value)

    def get_stage(self, material_class: MaterialClass) -> MaterialProcessStage:
        schema = self.get_schema(material_class)
        if not schema:
            return MaterialProcessStage.OTHER
        try:
            return MaterialProcessStage(schema.stage)
        except ValueError:
            return MaterialProcessStage.OTHER

    def label(self, material_class: MaterialClass, *, lang: str = "en") -> str:
        schema = self.get_schema(material_class)
        if not schema:
            return material_class.value
        if lang == "ru" and schema.label_ru:
            return schema.label_ru
        return schema.label

    def all_classes(self) -> list[MaterialClass]:
        return [MaterialClass(cid) for cid in self._ontology.material_classes if cid in MaterialClass._value2member_map_]

    def classes_for_stage(self, stage: MaterialProcessStage) -> list[MaterialClass]:
        return [cls for cls in self.all_classes() if self.get_stage(cls) == stage]

    def expand_classes(self, material_class: str | MaterialClass) -> list[str]:
        """Return class id plus siblings in the same process stage (for graph queries)."""
        try:
            cls = material_class if isinstance(material_class, MaterialClass) else MaterialClass(material_class)
        except ValueError:
            return [str(material_class)]
        stage = self.get_stage(cls)
        if stage == MaterialProcessStage.OTHER:
            return [cls.value]
        return [c.value for c in self.classes_for_stage(stage)]

    def coerce_class(
        self,
        raw: str | None,
        *,
        name: str = "",
        state: str | MaterialState | None = None,
    ) -> MaterialClass:
        """Map LLM output, aliases, or material name to a canonical class."""
        if raw:
            for token in re.split(r"[|/,;]+", raw.strip()):
                token = token.strip().lower().replace(" ", "_").replace("-", "_")
                if not token:
                    continue
                if token in self._alias_to_class:
                    return self._alias_to_class[token]
                spaced = token.replace("_", " ")
                if spaced in self._alias_to_class:
                    return self._alias_to_class[spaced]
                try:
                    return MaterialClass(token)
                except ValueError:
                    continue

            key = raw.strip().lower().replace(" ", "_").replace("-", "_")
            if key in self._alias_to_class:
                return self._alias_to_class[key]
            spaced = raw.strip().lower()
            if spaced in self._alias_to_class:
                return self._alias_to_class[spaced]
            try:
                return MaterialClass(key)
            except ValueError:
                pass

        inferred = self.infer_from_name(name, state=state)
        if inferred != MaterialClass.OTHER:
            return inferred

        if isinstance(state, MaterialState) and state == MaterialState.LIQUID:
            return MaterialClass.SOLUTION
        if state == "liquid":
            return MaterialClass.SOLUTION

        return MaterialClass.OTHER

    def infer_from_name(
        self,
        name: str,
        *,
        state: str | MaterialState | None = None,
    ) -> MaterialClass:
        if not name or len(name.strip()) < 2:
            return MaterialClass.OTHER

        lower = name.lower().strip()
        if isinstance(state, MaterialState) and state == MaterialState.LIQUID:
            if any(tok in lower for tok in ("electrolyte", "leachate", "liquor", "catholyte", "anolyte", "раствор")):
                return MaterialClass.SOLUTION

        scores: dict[MaterialClass, int] = {}
        for class_id, schema in self._ontology.material_classes.items():
            try:
                cls = MaterialClass(class_id)
            except ValueError:
                continue
            score = 0
            for pattern in schema.name_patterns:
                if pattern and pattern in lower:
                    score += 3 if len(pattern) >= 5 else 2
            for alias in schema.aliases:
                if len(alias) >= 4 and alias in lower:
                    score += 2
            if score:
                scores[cls] = score

        if not scores:
            return MaterialClass.OTHER
        return max(scores.items(), key=lambda item: item[1])[0]

    def prefer_class(self, current: MaterialClass, candidate: MaterialClass) -> MaterialClass:
        """Pick the more specific class when merging duplicate materials."""
        if current == candidate:
            return current
        if current == MaterialClass.OTHER:
            return candidate
        if candidate == MaterialClass.OTHER:
            return current
        return current if _CLASS_PRIORITY.get(current, 0) >= _CLASS_PRIORITY.get(candidate, 0) else candidate

    def prompt_block(self) -> str:
        lines = [
            "MATERIAL CLASSES (process-stream taxonomy — use exactly one per material):",
            "  Stage: Feedstock → Beneficiation → Processing → Product / Engineering",
        ]
        stage_order = [
            MaterialProcessStage.FEEDSTOCK,
            MaterialProcessStage.BENEFICIATION,
            MaterialProcessStage.PROCESSING,
            MaterialProcessStage.PRODUCT,
            MaterialProcessStage.ENGINEERING,
            MaterialProcessStage.OTHER,
        ]
        for stage in stage_order:
            classes = self.classes_for_stage(stage)
            if not classes:
                continue
            lines.append(f"  [{stage.value}]")
            for cls in classes:
                schema = self.get_schema(cls)
                if not schema:
                    continue
                examples = ", ".join(schema.aliases[:4]) if schema.aliases else schema.description[:60]
                lines.append(f"    - {cls.value}: {schema.label} — e.g. {examples}")
        allowed = ", ".join(c.value for c in self.all_classes())
        lines.append(f"  Allowed material_class values (pick exactly ONE per material): {allowed}")
        lines.append("  Return each material as a separate JSON object — never combine names with | or /.")
        lines.append(
            "  name = specific substance (nickel, copper matte, gypsum, catholyte) — "
            "NEVER put class labels (ore, concentrate, intermediate, metal, alloy) in name."
        )
        return "\n".join(lines)

    def find_materials_in_text(
        self,
        text: str,
        *,
        limit: int = 32,
    ) -> list[tuple[str, MaterialClass]]:
        """Word-boundary scan for taxonomy aliases/patterns (local LLM backfill)."""
        if not (text or "").strip():
            return []
        lower = text.lower()
        hits: dict[str, tuple[str, MaterialClass]] = {}
        for class_id, schema in self._ontology.material_classes.items():
            try:
                cls = MaterialClass(class_id)
            except ValueError:
                continue
            for term in list(schema.name_patterns or []) + list(schema.aliases or []):
                token = (term or "").strip()
                key = token.lower()
                if len(key) < 4 or is_generic_class_label(key):
                    continue
                if not re.search(rf"\b{re.escape(key)}\b", lower):
                    continue
                hits.setdefault(key, (token, cls))
                if len(hits) >= limit:
                    return list(hits.values())
        return list(hits.values())


def is_generic_class_label(name: str) -> bool:
    """
    True when `name` is a taxonomy category, not a real material.
    e.g. ore, concentrate, intermediate, ore|concentrate|intermediate
    """
    cleaned = (name or "").strip().lower()
    if not cleaned:
        return True

    if any(sep in cleaned for sep in ("|", ";", "/")):
        parts = [p.strip() for p in re.split(r"[|;,/]+", cleaned) if p.strip()]
        return bool(parts) and all(is_generic_class_label(part) for part in parts)

    if cleaned in _GENERIC_CLASS_LABELS:
        return True

    normalized = cleaned.replace(" ", "_").replace("-", "_")
    if normalized in MaterialClass._value2member_map_:
        return True

    tokens = [t for t in re.split(r"[\s_\-]+", cleaned) if t]
    if len(tokens) <= 1:
        return False

    return all(
        t in _GENERIC_CLASS_LABELS
        or t.replace("-", "_") in MaterialClass._value2member_map_
        for t in tokens
    )


def is_valid_material_name(name: str) -> bool:
    return not is_generic_class_label(name)


@lru_cache(maxsize=1)
def get_material_taxonomy() -> MaterialTaxonomy:
    return MaterialTaxonomy()


def coerce_material_class(
    raw: str | None,
    *,
    name: str = "",
    state: str | MaterialState | None = None,
) -> MaterialClass:
    return get_material_taxonomy().coerce_class(raw, name=name, state=state)
