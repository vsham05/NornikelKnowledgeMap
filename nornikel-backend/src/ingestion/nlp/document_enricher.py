"""Extract knowledge-graph entities for mining & metallurgy R&D documents."""

from __future__ import annotations

import logging
import re
from uuid import UUID, uuid4

from domain.dto.document import DocumentDTO
from domain.dto.experiment import ExperimentDTO, RegimeDTO, RegimeParameterDTO
from domain.dto.material import MaterialDTO
from domain.dto.property_value import PropertyValueDTO
from domain.enums import DOCUMENT_RELIABILITY, DocumentType, MaterialClass, MaterialState, RegimeType
from domain.material_taxonomy import get_material_taxonomy, is_valid_material_name
from ingestion.parsers.title_slide_extract import (
    extract_authors_from_text,
    extract_organizations_from_text,
    looks_like_person_name,
    merge_unique_names,
)
from ingestion.nlp.material_process_linker import build_material_process_links
from ingestion.nlp.extraction_validate import (
    is_llm_template_string,
    is_placeholder_equipment,
    is_placeholder_expert_field,
    is_placeholder_process,
    is_placeholder_topic,
    normalize_entity_name,
)
from ingestion.nlp.entity_normalize import (
    coerce_material_class,
    coerce_material_state,
    split_compound_field,
)
from infra.llm_client import LLMClient
from settings import Settings

logger = logging.getLogger(__name__)

_SAMPLE_CHARS = 28_000

_PLACEHOLDER_TEAM_NAMES = frozenset({
    "lab or company",
    "lab",
    "company",
    "laboratory",
    "research team",
    "team name",
    "organization",
    "research group",
    "company name",
    "team",
})

_PLACEHOLDER_FACILITY_NAMES = frozenset({
    "plant or laboratory",
    "plant or lab",
    "plant or company",
    "plant",
    "laboratory",
    "lab",
    "facility",
    "site",
    "location",
    "factory",
    "works",
    "plant or facility",
})

_PROCESS_TOPIC_PHRASES = (
    "water treatment",
    "catholyte circulation",
    "heap leaching",
    "mine water",
    "wastewater",
    "effluent treatment",
    "flotation circuit",
    "electrowinning",
)


class DocumentEnricher:
    """One LLM pass per document → full R&D knowledge map entities."""

    def __init__(self, settings: Settings):
        self.llm_client = LLMClient(settings)

    async def enrich_document(self, document: DocumentDTO) -> dict:
        self._augment_document_provenance(document)
        text = self._sample_text(document)
        if len(text.strip()) < 80:
            return self._empty()

        prompt = self._build_prompt(document, text)
        try:
            raw = await self.llm_client.chat_json(user_message=prompt, temperature=0.1)
        except Exception as exc:
            logger.warning("Document enricher LLM failed: %s", exc)
            return self._empty()

        geography = self._parse_geography(raw.get("geography") or {})
        materials = self._parse_materials(raw.get("materials") or raw.get("entities") or [], document.id)
        processes = self._parse_processes(raw.get("processes") or [], document.id)
        material_process_links = build_material_process_links(
            materials, processes, text
        )
        equipment = self._parse_named_list(raw.get("equipment") or [], "equipment")
        facilities = self._parse_facilities(
            raw.get("facilities") or [], geography
        )
        raw_teams = self._coerce_team_raw(raw)
        raw_team_members = self._collect_raw_team_members(raw_teams)
        teams = self._parse_teams(raw_teams, document)
        experts = self._parse_experts(
            raw.get("experts") or [],
            teams,
            document,
            extra_members=raw_team_members,
        )
        self._link_experts_to_team(experts, teams)
        self._sync_team_members(teams, experts)
        topics = [
            t for t in (str(t).strip() for t in (raw.get("topics") or []))
            if t and not is_placeholder_topic(t)
        ]

        primary_process = processes[0]["id"] if processes else None
        process_by_name = {p["name"].lower(): p["id"] for p in processes}
        experiments, extra_topics = self._parse_findings(
            raw.get("findings") or [],
            document.id,
            materials,
            process_by_name,
        )
        for topic in extra_topics:
            if topic not in topics and not is_placeholder_topic(topic):
                topics.append(topic)

        reliability = DOCUMENT_RELIABILITY.get(
            document.document_type.value,
            DOCUMENT_RELIABILITY[DocumentType.OTHER.value],
        )

        logger.info(
            "Enricher: %s mat, %s exp, %s proc, %s eq, %s fac, %s teams, %s experts",
            len(materials), len(experiments), len(processes),
            len(equipment), len(facilities), len(teams), len(experts),
        )
        return {
            "materials": materials,
            "experiments": experiments,
            "topics": topics,
            "teams": teams,
            "processes": processes,
            "equipment": equipment,
            "facilities": facilities,
            "experts": experts,
            "geography": geography,
            "reliability": reliability,
            "material_process_links": material_process_links,
        }

    def _sample_text(self, document: DocumentDTO) -> str:
        parts: list[str] = []
        total = 0
        for chunk in document.chunks:
            piece = (chunk.text or "").strip()
            if not piece:
                continue
            parts.append(piece)
            total += len(piece)
            if total >= _SAMPLE_CHARS:
                break
        return "\n\n".join(parts)[:_SAMPLE_CHARS]

    def _augment_document_provenance(self, document: DocumentDTO) -> None:
        """Merge authors/orgs from document text into the DTO."""
        parts: list[str] = []
        total = 0
        for chunk in document.chunks:
            piece = (chunk.text or "").strip()
            if not piece:
                continue
            parts.append(piece)
            total += len(piece)
            if total >= 12_000:
                break
        slide_text = "\n\n".join(parts)

        if slide_text:
            document.authors = merge_unique_names(
                document.authors,
                extract_authors_from_text(slide_text, 12_000),
            )
            document.organizations = merge_unique_names(
                document.organizations,
                extract_organizations_from_text(slide_text, 12_000),
            )

    @staticmethod
    def _collect_raw_team_members(raw_teams: list) -> list[str]:
        members: list[str] = []
        for item in raw_teams:
            if not isinstance(item, dict):
                continue
            for key in ("members", "authors"):
                val = item.get(key)
                if isinstance(val, list):
                    members.extend(str(m) for m in val if m)
                elif isinstance(val, str) and val.strip():
                    members.append(val)
        return members

    def _build_prompt(self, document: DocumentDTO, text: str) -> str:
        taxonomy = get_material_taxonomy().prompt_block()
        author_hint = ""
        if document.authors:
            author_hint = (
                "\nKnown authors (from document metadata / title slide): "
                + ", ".join(document.authors[:15])
            )
        org_hint = ""
        if document.organizations:
            org_hint = (
                "\nKnown organizations (from title slide): "
                + ", ".join(document.organizations[:5])
            )
        return f"""Analyze this mining/metallurgy R&D document and extract a knowledge graph as JSON.
Domain: hydrometallurgy, pyrometallurgy, electrowinning, leaching, flotation, ecology, waste recycling.
Russian or English text.

{taxonomy}

Title: {document.title}{author_hint}{org_hint}

Return ONLY valid JSON with this shape (use empty arrays when not stated in the document):
{{
  "geography": {{"country": null, "scope": null}},
  "materials": [],
  "processes": [],
  "equipment": [],
  "facilities": [],
  "experts": [],
  "findings": [],
  "topics": [],
  "teams": []
}}

Each array item when present:
- materials: {{"name": "...", "aliases": [], "material_class": "<taxonomy id>"}}
- processes: {{"name": "...", "aliases": [], "materials": ["<material names handled in this process>"]}}
- equipment: {{"name": "..."}}
- facilities: {{"name": "...", "country": "...", "facility_type": "plant|mine|smelter|refinery|laboratory|site"}}
- experts: {{"name": "...", "field": "..."}}
- teams: {{"name": "<institute/company>", "members": ["..."]}}
- findings: {{"title": "...", "topic": "...", "process": "...", "summary": "...", "status": "completed|ongoing|planned", "parameters": {{}}}}

Rules:
- materials: list EVERY distinct substance mentioned (nickel, copper matte, gypsum, catholyte, matte, slag…)
- name = specific chemical/material name only — NOT category words (ore, concentrate, intermediate, metal, alloy go in material_class)
- one material per JSON object — never join names with | or /
- material_class: exactly one value from the allowed list
- processes: technological operations only (not material names)
- for each process, list material names that are inputs/outputs/intermediates of that process in materials[]
- teams: REQUIRED when authors or affiliation appear — research lab / institute / company name (not a person name)
- team.members: all author names from the document
- experts: every individual researcher named (all team.members + any other named scientists)
- facilities: specific plants, mines, smelters, or laboratories (named site + country) — NOT generic "plant or laboratory" and NOT process topics like "mine water treatment"
- facility_type: plant | mine | smelter | refinery | laboratory | site
- findings: 1-6 experiments, results, or confirmed conclusions with numeric parameters when present
- geography.scope: domestic | international | global — only if clearly stated; otherwise null
- If a field is not mentioned in the document, return an empty array [] or null — never copy example or placeholder text

Text:
{text}
"""

    def _parse_geography(self, raw: dict) -> dict:
        country_raw = str(raw.get("country") or "").strip()
        country = country_raw or None
        if country and is_llm_template_string(country):
            country = None
        scope_raw = str(raw.get("scope") or "").lower().strip()
        scope = scope_raw if scope_raw in ("domestic", "international", "global") else None
        return {"country": country, "scope": scope}

    def _parse_materials(self, raw_entities: list, document_id: UUID) -> list[MaterialDTO]:
        materials: list[MaterialDTO] = []
        seen: set[str] = set()
        for item in raw_entities:
            if not isinstance(item, dict):
                raw_names = split_compound_field(str(item))
                aliases: list[str] = []
                mat_class_raw = None
            else:
                raw_names = split_compound_field(str(item.get("name") or ""))
                aliases = [str(a) for a in item.get("aliases") or [] if a]
                mat_class_raw = item.get("material_class")
            for name in raw_names:
                if not name or not is_valid_material_name(name):
                    logger.debug("Skipping invalid material name (class label): %s", name)
                    continue
                if is_llm_template_string(name):
                    logger.debug("Skipping template material name: %s", name)
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                mat_class = coerce_material_class(mat_class_raw, name=name)
                state = coerce_material_state(
                    item.get("state") if isinstance(item, dict) else None
                )
                materials.append(
                    MaterialDTO(
                        id=uuid4(),
                        name=name,
                        aliases=aliases,
                        material_class=mat_class,
                        state=state,
                        properties={},
                        source_document_id=document_id,
                    )
                )
        return materials[:30]

    def _parse_processes(self, raw: list, document_id: UUID) -> list[dict]:
        processes: list[dict] = []
        seen: set[str] = set()
        for item in raw:
            if isinstance(item, dict):
                raw_names = split_compound_field(str(item.get("name") or ""))
                aliases = [str(a) for a in item.get("aliases") or [] if a]
            else:
                raw_names = split_compound_field(str(item))
                aliases = []
            for name in raw_names:
                if not name or name.lower() in seen:
                    continue
                if is_llm_template_string(name) or is_placeholder_process(name):
                    logger.debug("Skipping invalid process name: %s", name)
                    continue
                seen.add(name.lower())
                proc_materials: list[str] = []
                if isinstance(item, dict):
                    for m in item.get("materials") or []:
                        mname = str(m).strip()
                        if mname and not is_llm_template_string(mname):
                            proc_materials.append(mname)
                processes.append({
                    "id": str(uuid4()),
                    "name": name,
                    "aliases": aliases,
                    "materials": proc_materials,
                    "document_id": str(document_id),
                })
        return processes[:12]

    def _parse_named_list(self, raw: list, kind: str) -> list[dict]:
        items: list[dict] = []
        seen: set[str] = set()
        for item in raw:
            raw_names = split_compound_field(
                str(item.get("name") if isinstance(item, dict) else item)
            )
            for name in raw_names:
                if not name or name.lower() in seen:
                    continue
                if is_llm_template_string(name) or is_placeholder_equipment(name):
                    logger.debug("Skipping invalid equipment name: %s", name)
                    continue
                seen.add(name.lower())
                items.append({"id": str(uuid4()), "name": name, "kind": kind})
        return items[:12]

    def _is_placeholder_facility_name(self, name: str) -> bool:
        n = name.strip().lower()
        if n in _PLACEHOLDER_FACILITY_NAMES:
            return True
        return "plant or laboratory" in n or "plant or lab" in n

    def _is_process_topic_not_facility(self, name: str) -> bool:
        lower = name.strip().lower()
        if self._looks_like_person(lower):
            return True
        if any(phrase in lower for phrase in _PROCESS_TOPIC_PHRASES):
            return True
        facility_hints = (
            "plant", "mine", "mill", "smelter", "refinery", "laboratory", "lab",
            "mmc", "division", "works", "гок", "комбинат", "завод", "рудник",
            "фабрика", "комплекс", "norilsk", "monchegorsk", "zapolyarny",
        )
        if any(h in lower for h in facility_hints):
            return False
        return len(lower.split()) <= 3 and not any(c.isupper() for c in name[1:])

    def _parse_facilities(self, raw: list, geography: dict) -> list[dict]:
        facilities: list[dict] = []
        seen: set[str] = set()
        valid_types = {"plant", "mine", "smelter", "refinery", "laboratory", "site"}

        for item in raw:
            if not isinstance(item, dict):
                continue
            raw_names = split_compound_field(str(item.get("name") or ""))
            country_raw = str(item.get("country") or "").strip()
            country = country_raw or None
            if country and is_llm_template_string(country):
                country = None
            facility_type = str(item.get("facility_type") or "").strip().lower() or None
            if facility_type and facility_type not in valid_types:
                facility_type = None
            for name in raw_names:
                if not name or name.lower() in seen:
                    continue
                if is_llm_template_string(name):
                    logger.debug("Skipping template facility name: %s", name)
                    continue
                if (
                    self._is_placeholder_facility_name(name)
                    or self._is_process_topic_not_facility(name)
                ):
                    logger.debug("Skipping invalid facility name: %s", name)
                    continue
                seen.add(name.lower())
                facilities.append({
                    "id": str(uuid4()),
                    "name": name,
                    "country": country,
                    "facility_type": facility_type,
                })

        return facilities[:4]

    def _coerce_team_raw(self, raw: dict) -> list:
        teams = raw.get("teams")
        if isinstance(teams, list) and teams:
            return teams
        org = (
            raw.get("organization")
            or raw.get("organisation")
            or raw.get("affiliation")
            or raw.get("institution")
        )
        if isinstance(org, str) and org.strip():
            return [{"name": org.strip(), "members": raw.get("authors") or []}]
        if isinstance(org, dict) and org.get("name"):
            return [org]
        return []

    @staticmethod
    def _split_person_names(values: list[str] | str | None) -> list[str]:
        if not values:
            return []
        if isinstance(values, str):
            values = [values]
        names: list[str] = []
        for value in values:
            text = str(value).strip()
            if not text:
                continue
            for part in re.split(r"[;/\n]|(?:\s+and\s+)", text):
                cleaned = re.sub(r"\s+", " ", part.strip(" .;,"))
                if cleaned:
                    names.append(cleaned)
        return names

    @staticmethod
    def _person_identity_key(name: str) -> str:
        parts = [p.strip(".") for p in re.sub(r"\s+", " ", name.strip()).lower().split()]
        if len(parts) >= 2:
            return f"{parts[0]}_{parts[-1]}"
        return name.strip().lower()

    def _looks_like_person(self, name: str) -> bool:
        return looks_like_person_name(name)

    def _looks_like_org_name(self, name: str) -> bool:
        from ingestion.parsers.title_slide_extract import looks_like_organization_name

        if self._is_placeholder_team_name(name):
            return False
        return looks_like_organization_name(name)

    def _sync_team_members(self, teams: list[dict], experts: list[dict]) -> None:
        for team in teams:
            linked = [e["name"] for e in experts if e.get("team_id") == team["id"]]
            team["members"] = self._merge_member_lists(team.get("members") or [], linked)

    def _is_placeholder_team_name(self, name: str) -> bool:
        n = name.strip().lower()
        return n in _PLACEHOLDER_TEAM_NAMES or "lab or company" in n

    @staticmethod
    def _merge_member_lists(*lists: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for lst in lists:
            for name in lst:
                key = name.strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append(name.strip())
        return out

    def _link_experts_to_team(self, experts: list[dict], teams: list[dict]) -> None:
        if not teams:
            return
        team_id = teams[0]["id"]
        for expert in experts:
            if not expert.get("team_id"):
                expert["team_id"] = team_id

    def _parse_experts(
        self,
        raw: list,
        teams: list[dict],
        document: DocumentDTO,
        extra_members: list[str] | None = None,
    ) -> list[dict]:
        experts: list[dict] = []
        seen: set[str] = set()

        def add_expert(name: str, field: str | None = None, *, from_llm: bool = False) -> None:
            cleaned = normalize_entity_name(name)
            if not cleaned or is_llm_template_string(cleaned):
                return
            if from_llm:
                if self._looks_like_org_name(cleaned):
                    return
                parts = cleaned.split()
                if len(parts) < 2 or len(cleaned) > 80:
                    return
            elif not self._looks_like_person(cleaned):
                return
            field_clean = normalize_entity_name(field) if field else None
            if field_clean and is_placeholder_expert_field(field_clean):
                field_clean = None
            key = self._person_identity_key(cleaned)
            if key in seen:
                return
            seen.add(key)
            experts.append({
                "id": str(uuid4()),
                "name": cleaned,
                "field": field_clean,
                "team_id": None,
            })

        for item in raw:
            if not isinstance(item, dict):
                continue
            add_expert(
                str(item.get("name") or ""),
                str(item.get("field") or "").strip() or None,
                from_llm=True,
            )

        for team in teams:
            for member in team.get("members") or []:
                add_expert(str(member))

        for author in self._split_person_names(document.authors):
            add_expert(author)

        for member in self._split_person_names(extra_members or []):
            add_expert(str(member))

        return experts[:20]

    def _pick_material_for_finding(
        self, item: dict, materials: list[MaterialDTO]
    ) -> UUID | None:
        if not materials:
            return None
        haystack = " ".join(
            str(item.get(key) or "")
            for key in ("title", "topic", "process", "summary")
        ).lower()
        for mat in materials:
            if mat.name.lower() in haystack:
                return mat.id
        for mat in materials:
            for alias in mat.aliases:
                if alias.lower() in haystack:
                    return mat.id
        return None

    def _parse_findings(
        self,
        raw_findings: list,
        document_id: UUID,
        materials: list[MaterialDTO],
        process_by_name: dict[str, str],
    ) -> tuple[list[ExperimentDTO], list[str]]:
        experiments: list[ExperimentDTO] = []
        topics: list[str] = []

        for item in raw_findings:
            if not isinstance(item, dict):
                continue
            if not materials:
                continue
            title = str(item.get("title") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if not title and not summary:
                continue
            if title and is_llm_template_string(title):
                title = ""
            if summary and is_llm_template_string(summary):
                summary = ""
            if not title and not summary:
                continue
            label = title or summary

            topic = str(item.get("topic") or "").strip()
            if topic and not is_placeholder_topic(topic) and topic not in topics:
                topics.append(topic)

            status_raw = str(item.get("status") or "").lower().strip()
            status = status_raw if status_raw in ("completed", "ongoing", "planned") else None

            params: dict[str, RegimeParameterDTO] = {}
            if status:
                params["status"] = RegimeParameterDTO(
                    name="status",
                    value=PropertyValueDTO(value=status, unit=""),
                )
            raw_params = item.get("parameters") or {}
            if isinstance(raw_params, dict):
                for pname, pval in list(raw_params.items())[:6]:
                    if not isinstance(pval, dict):
                        continue
                    val = str(pval.get("value", "")).strip()
                    if not val:
                        continue
                    params[str(pname)] = RegimeParameterDTO(
                        name=str(pname),
                        value=PropertyValueDTO(
                            value=val,
                            unit=str(pval.get("unit") or ""),
                            value_min=pval.get("min"),
                            value_max=pval.get("max"),
                        ),
                    )

            material_id = self._pick_material_for_finding(item, materials)
            if material_id is None:
                continue

            process_name = str(item.get("process") or topic or "").strip().lower()
            linked_process_id = process_by_name.get(process_name) if process_name else None

            exp = ExperimentDTO(
                id=uuid4(),
                material_id=material_id,
                regime=RegimeDTO(
                    regime_type=RegimeType.OTHER,
                    name=(topic or label)[:80],
                    parameters=params,
                    description=(summary or label)[:500],
                ),
                conclusions=[(summary or label)[:500]],
                document_id=document_id,
            )
            if linked_process_id:
                exp.__dict__["_process_id"] = linked_process_id
            experiments.append(exp)
        return experiments[:10], topics[:12]

    def _parse_teams(
        self,
        raw_teams: list,
        document: DocumentDTO,
    ) -> list[dict]:
        teams: list[dict] = []
        seen: set[str] = set()
        doc_authors = self._split_person_names(document.authors)

        for item in raw_teams:
            if not isinstance(item, dict):
                continue
            name = str(
                item.get("name")
                or item.get("organization")
                or item.get("institution")
                or item.get("affiliation")
                or ""
            ).strip()
            if not name or name.lower() in seen:
                continue
            if self._looks_like_person(name) or self._is_placeholder_team_name(name):
                logger.debug("Skipping invalid team name: %s", name)
                continue
            if is_llm_template_string(name):
                logger.debug("Skipping template team name: %s", name)
                continue
            seen.add(name.lower())
            item_members = self._split_person_names(item.get("members") or item.get("authors"))
            teams.append({
                "id": str(uuid4()),
                "name": name,
                "members": self._merge_member_lists(item_members, doc_authors),
            })

        if not teams:
            for org in document.organizations or []:
                name = str(org).strip()
                if not name or name.lower() in seen:
                    continue
                if self._looks_like_person(name) or self._is_placeholder_team_name(name):
                    continue
                if is_llm_template_string(name):
                    continue
                if not self._looks_like_org_name(name):
                    continue
                seen.add(name.lower())
                teams.append({
                    "id": str(uuid4()),
                    "name": name,
                    "members": list(doc_authors),
                })
                break

        return teams[:3]

    def _empty(self) -> dict:
        return {
            "materials": [],
            "experiments": [],
            "topics": [],
            "teams": [],
            "processes": [],
            "equipment": [],
            "facilities": [],
            "experts": [],
            "geography": {"country": None, "scope": None},
            "reliability": None,
            "material_process_links": [],
        }
