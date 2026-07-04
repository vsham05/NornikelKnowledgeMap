"""Extract knowledge-graph entities for mining & metallurgy R&D documents."""

from __future__ import annotations

import asyncio
import logging
import math
import re
from uuid import UUID, uuid4

from domain.dto.document import DocumentDTO
from domain.dto.experiment import ExperimentDTO, RegimeDTO, RegimeParameterDTO
from domain.dto.material import MaterialDTO
from domain.dto.property_value import PropertyValueDTO
from domain.enums import DOCUMENT_RELIABILITY, DocumentType, MaterialClass, MaterialState, RegimeType
from domain.material_taxonomy import get_material_taxonomy, is_valid_material_name
from domain.entity_glossary import (
    FACILITY_GLOSSARY_KEYS,
    PROCESS_GLOSSARY_KEYS,
    canonical_entity_key,
    find_glossary_terms_in_text,
)
from ingestion.parsers.title_slide_extract import (
    extract_authors_from_text,
    extract_authors_from_document_chunks,
    extract_listed_experts_from_text,
    extract_organizations_from_text,
    looks_like_author_name,
    looks_like_affiliation_name,
    looks_like_person_name,
    merge_unique_names,
    normalize_person_name,
)
from ingestion.nlp.material_process_linker import build_material_process_links
from ingestion.nlp.extraction_validate import (
    is_blocklisted_entity_name,
    is_llm_template_string,
    is_placeholder_equipment,
    is_placeholder_expert_field,
    is_placeholder_process,
    is_placeholder_topic,
    looks_like_section_heading,
    normalize_entity_name,
    pick_monolingual_label,
)
from ingestion.nlp.extraction_language import (
    extraction_language_instruction,
    resolve_extraction_language,
)
from ingestion.nlp.text_language_normalize import normalize_extraction_payload
from ingestion.nlp.entity_normalize import (
    coerce_material_class,
    coerce_material_state,
    split_compound_field,
)
from ingestion.chunking import stratified_document_text
from infra.extraction_limits import resolve_extraction_max_chars
from infra.local_models import (
    is_high_capability_local,
    local_enricher_concurrency,
    local_ingest_profile,
)
from infra.llm_client import LLMClient
from infra.llm_runtime import get_effective_llm_provider, get_local_model
from settings import Settings

logger = logging.getLogger(__name__)

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
        self.settings = settings
        self.llm_client = LLMClient(settings)

    async def enrich_document(
        self,
        document: DocumentDTO,
        *,
        fast_mode: bool = False,
        multipass: int = 0,
    ) -> dict:
        configured = int(multipass or 0)
        passes = configured if configured > 0 else self._coverage_pass_count(document, fast_mode=fast_mode)
        if passes <= 1:
            return await self._enrich_document_once(document, fast_mode=fast_mode)

        chunks = [c for c in document.chunks if (c.text or "").strip()]
        if len(chunks) < 2:
            return await self._enrich_document_once(document, fast_mode=fast_mode)

        logger.info("Enricher full coverage: %s passes across %s chunks", passes, len(chunks))
        section_texts: list[str] = []
        n = len(chunks)
        for section in range(passes):
            start = int(n * section / passes)
            end = int(n * (section + 1) / passes)
            text = self._sample_section_text(chunks[start:end], fast_mode=fast_mode)
            if len(text.strip()) >= 80:
                section_texts.append(text)

        if not section_texts:
            return await self._enrich_document_once(document, fast_mode=fast_mode)

        concurrency = local_enricher_concurrency(
            get_local_model(),
            configured=int(self.settings.ingest_local_enricher_concurrency or 0),
        )
        if get_effective_llm_provider() == "yandex":
            concurrency = min(8, max(concurrency, 4))

        sem = asyncio.Semaphore(concurrency)

        async def run_section(text: str) -> dict:
            async with sem:
                return await self._enrich_document_once(
                    document,
                    fast_mode=fast_mode,
                    text_override=text,
                )

        partials = await asyncio.gather(*(run_section(text) for text in section_texts))
        merged = partials[0]
        for partial in partials[1:]:
            merged = self._merge_enrichment(merged, partial)
        return merged

    def _coverage_pass_count(self, document: DocumentDTO, *, fast_mode: bool) -> int:
        """How many enricher passes are needed to read the whole document."""
        chunks = [c for c in document.chunks if (c.text or "").strip()]
        if len(chunks) <= 12:
            return 1

        pages = self._document_page_count(document)
        if get_effective_llm_provider() == "yandex":
            # 64k+ context per call — avoid dozens of sequential API round-trips
            if pages <= 80:
                return 1
            if pages <= 180:
                return 2
            return min(4, max(2, math.ceil(pages / 120)))

        max_chars = self._enricher_sample_max_chars(fast_mode=fast_mode)
        total = sum(len(c.text or "") for c in chunks)
        passes = max(1, math.ceil(total / max(1, max_chars)))
        return min(len(chunks), passes)

    @staticmethod
    def _document_page_count(document: DocumentDTO) -> int:
        if not document.chunks:
            return 0
        return max((c.page_number or 0) for c in document.chunks)

    @staticmethod
    def _is_proceedings_volume(document: DocumentDTO) -> bool:
        """Multi-paper proceedings — avoid harvesting every paper's header as experts."""
        if not document.chunks:
            return False
        pages = max((c.page_number or 0) for c in document.chunks)
        return pages >= 35 or len(document.chunks) >= 35

    async def _enrich_document_once(
        self,
        document: DocumentDTO,
        *,
        fast_mode: bool = False,
        text_override: str | None = None,
    ) -> dict:
        self._augment_document_provenance(document)
        text = text_override if text_override is not None else self._sample_text(document, fast_mode=fast_mode)
        if len(text.strip()) < 80:
            return self._empty()

        prompt = self._build_prompt(document, text)
        target_lang = resolve_extraction_language(text, self.settings.extraction_language)
        profile = local_ingest_profile(get_local_model())
        enrich_max_tokens = profile["max_output_tokens"]
        if get_effective_llm_provider() == "yandex" and not fast_mode:
            enrich_max_tokens = 32_768
        elif get_effective_llm_provider() == "yandex":
            enrich_max_tokens = 24_576
        elif is_high_capability_local(get_local_model()) and not fast_mode:
            enrich_max_tokens = min(profile["max_output_tokens"] + 4096, 20_480)
        try:
            raw = await self.llm_client.chat_json(
                user_message=prompt,
                temperature=0.0,
                target_lang=target_lang,
                max_tokens=enrich_max_tokens,
            )
        except Exception as exc:
            logger.warning("Document enricher LLM failed: %s", exc)
            return self._empty()

        try:
            raw = await normalize_extraction_payload(
                raw,
                text,
                self.llm_client,
                target_lang=target_lang,
                fast_mode=(
                    fast_mode
                    or get_effective_llm_provider() == "local"
                    or get_effective_llm_provider() == "yandex"
                    or is_high_capability_local(get_local_model())
                ),
            )
        except Exception as exc:
            logger.warning("Document enricher language normalize failed: %s", exc)

        raw = self._reclassify_mislabeled_entities(raw)

        geography = self._parse_geography(raw.get("geography") or {})
        materials = self._parse_materials(
            raw.get("materials") or raw.get("entities") or [],
            document.id,
            target_lang,
        )
        full_text = self._full_document_text(document)
        materials = self._backfill_materials_from_text(
            materials, full_text, document.id, target_lang
        )
        processes = self._parse_processes(
            raw.get("processes") or [], document.id, target_lang
        )
        processes = self._backfill_processes_from_text(
            processes, full_text, document.id, target_lang
        )
        material_process_links = build_material_process_links(
            materials, processes, text
        )
        equipment = self._parse_named_list(raw.get("equipment") or [], "equipment")
        facilities = self._parse_facilities(raw.get("facilities") or [], geography)
        facilities = self._backfill_facilities_from_text(facilities, full_text, geography)
        raw_teams = self._coerce_team_raw(raw)
        raw_team_members = self._collect_raw_team_members(raw_teams)
        teams = self._parse_teams(raw_teams, document)
        entity_blocklist = self._entity_name_blocklist(
            materials, processes, equipment, facilities, teams
        )
        experts = self._parse_experts(
            raw.get("experts") or [],
            teams,
            document,
            extra_members=raw_team_members,
            blocklist=entity_blocklist,
        )
        self._link_experts_to_team(experts, teams)
        self._sync_team_members(teams, experts)
        topics = [
            t for t in (str(t).strip() for t in (raw.get("topics") or []))
            if t and not is_placeholder_topic(t)
        ]

        primary_process = processes[0]["id"] if processes else None
        process_by_name: dict[str, str] = {}
        for p in processes:
            process_by_name[p["name"].lower()] = p["id"]
            if p.get("canonical_key"):
                process_by_name[p["canonical_key"]] = p["id"]
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

    def _full_document_text(self, document: DocumentDTO, max_chars: int | None = None) -> str:
        parts: list[str] = []
        total = 0
        for chunk in document.chunks:
            piece = (chunk.text or "").strip()
            if not piece:
                continue
            parts.append(piece)
            total += len(piece) + 2
            if max_chars is not None and total >= max_chars:
                break
        joined = "\n\n".join(parts)
        return joined[:max_chars] if max_chars is not None else joined

    def _enricher_sample_max_chars(self, *, fast_mode: bool) -> int:
        base = resolve_extraction_max_chars(self.settings)
        if get_effective_llm_provider() == "yandex":
            return base
        if not fast_mode:
            profile = local_ingest_profile(get_local_model())
            if profile.get("tier") == "light":
                return min(base * 2, 20_000)
            return base
        if is_high_capability_local(get_local_model()):
            return min(base, 32_000)
        return min(base * 2, 24_000)

    def _sample_text(self, document: DocumentDTO, *, fast_mode: bool = False) -> str:
        max_chars = self._enricher_sample_max_chars(fast_mode=fast_mode)
        chunks = [c for c in document.chunks if (c.text or "").strip()]
        pages = self._document_page_count(document)
        profile = local_ingest_profile(get_local_model())
        if pages >= 200:
            sample_points = 56
        elif pages >= 80:
            sample_points = 48
        elif pages >= 35:
            sample_points = 40
        elif fast_mode:
            sample_points = 24
        elif profile.get("tier") == "light":
            sample_points = 32
        else:
            sample_points = 20
        return stratified_document_text(
            chunks,
            max_chars=max_chars,
            sample_points=sample_points,
        )

    def _backfill_materials_from_text(
        self,
        materials: list[MaterialDTO],
        text: str,
        document_id: UUID,
        target_lang: str,
    ) -> list[MaterialDTO]:
        """Merge taxonomy hits missing from local 7B LLM JSON."""
        if not text.strip():
            return materials
        existing = {m.name.lower() for m in materials}
        taxonomy = get_material_taxonomy()
        added = 0
        for name, mat_class in taxonomy.find_materials_in_text(text):
            key = name.lower()
            if key in existing or not is_valid_material_name(name):
                continue
            materials.append(
                MaterialDTO(
                    id=uuid4(),
                    name=pick_monolingual_label(name, target_lang),
                    material_class=mat_class,
                    state=MaterialState.SOLID,
                    properties={},
                    source_document_id=document_id,
                )
            )
            existing.add(key)
            added += 1
        if added:
            logger.info("Local backfill: added %s materials from taxonomy scan", added)
        return materials

    def _backfill_processes_from_text(
        self,
        processes: list[dict],
        text: str,
        document_id: UUID,
        target_lang: str,
    ) -> list[dict]:
        if not text.strip():
            return processes
        seen = {str(p.get("canonical_key") or "").lower() for p in processes}
        added = 0
        for key, ru, en in find_glossary_terms_in_text(text, PROCESS_GLOSSARY_KEYS):
            if key in seen:
                continue
            display = en if target_lang == "en" else ru
            if not display:
                display = en or ru
            seen.add(key)
            processes.append({
                "id": str(uuid4()),
                "name": display,
                "canonical_key": key,
                "aliases": [],
                "materials": [],
                "document_id": str(document_id),
            })
            added += 1
        if added:
            logger.info("Glossary backfill: added %s processes from text scan", added)
        return processes

    def _backfill_facilities_from_text(
        self,
        facilities: list[dict],
        text: str,
        geography: dict,
    ) -> list[dict]:
        if not text.strip():
            return facilities
        seen = {str(f.get("name") or "").lower() for f in facilities}
        added = 0
        for key, ru, en in find_glossary_terms_in_text(text, FACILITY_GLOSSARY_KEYS):
            name = en or ru
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            facilities.append({
                "id": str(uuid4()),
                "name": name,
                "country": geography.get("country"),
                "facility_type": "site",
            })
            added += 1
        if added:
            logger.info("Glossary backfill: added %s facilities from text scan", added)
        return facilities

    def _sample_section_text(
        self, chunks: list, *, fast_mode: bool = False
    ) -> str:
        max_chars = self._enricher_sample_max_chars(fast_mode=fast_mode)
        parts: list[str] = []
        total = 0
        for chunk in chunks:
            piece = (chunk.text or "").strip()
            if not piece:
                continue
            parts.append(piece)
            total += len(piece)
            if total >= max_chars:
                break
        return "\n\n".join(parts)[:max_chars]

    def _augment_document_provenance(self, document: DocumentDTO) -> None:
        """Merge authors/orgs from document text into the DTO."""
        slide_text = self._full_document_text(document)

        if slide_text:
            document.authors = merge_unique_names(
                document.authors,
                extract_authors_from_text(slide_text, len(slide_text) or 2_000_000),
            )
            document.authors = merge_unique_names(
                document.authors,
                extract_listed_experts_from_text(slide_text, len(slide_text) or 2_000_000),
            )
            proceedings = self._is_proceedings_volume(document)
            if proceedings:
                document.authors = merge_unique_names(
                    document.authors,
                    extract_authors_from_document_chunks(
                        document.chunks,
                        max_authors=0,
                    ),
                )
            else:
                document.authors = merge_unique_names(
                    document.authors,
                    extract_authors_from_document_chunks(document.chunks),
                )
            document.organizations = merge_unique_names(
                document.organizations,
                extract_organizations_from_text(slide_text, 40_000),
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
        target_lang = resolve_extraction_language(text, self.settings.extraction_language)
        return self._build_prompt_default(document, text, target_lang)

    def _build_prompt_default(self, document: DocumentDTO, text: str, target_lang: str) -> str:
        taxonomy = get_material_taxonomy().prompt_block()
        author_hint = ""
        if document.authors:
            author_hint = (
                "\nKnown authors (from document metadata / title slide): "
                + ", ".join(document.authors)
            )
        org_hint = ""
        if document.organizations:
            org_hint = (
                "\nKnown organizations (from title slide): "
                + ", ".join(document.organizations)
            )
        proceedings = self._is_proceedings_volume(document)
        findings_rule = (
            "- findings: extract EVERY distinct experiment, operating condition set, and numeric result in the sampled section"
            if proceedings
            else "- findings: extract every experiment, operating condition, and confirmed conclusion with numeric parameters"
        )
        recall_rule = ""
        if get_effective_llm_provider() == "local":
            recall_rule = (
                "\n- LOCAL RECALL MODE: list every material, process, facility, equipment, expert, "
                "team, and finding visible in the text — prefer completeness over short JSON"
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
- experts: ONLY individual human names (authors / researchers) in "First Last" or "Last First Patronymic" form
- For conference proceedings volumes: prefer expert roster / title-slide authors; still include paper authors when clearly named in the sampled section
- NEVER put organizations, materials, processes, equipment, or facilities in experts — use teams/materials/processes/equipment/facilities instead
- facilities: specific plants, mines, smelters, or laboratories (named site + country) — NOT generic "plant or laboratory" and NOT process topics like "mine water treatment"
- facility_type: plant | mine | smelter | refinery | laboratory | site
{findings_rule}
- Be exhaustive: list every distinct material, process, facility, equipment, and finding mentioned in the sampled text{recall_rule}
- Keep JSON compact: no duplicate entities, no prose outside JSON
- {extraction_language_instruction(target_lang)}
- Property keys in parameters stay English snake_case (nickel_content, recovery_rate)
- geography.scope: domestic | international | global — only if clearly stated; otherwise null
- If a field is not mentioned in the document, return an empty array [] or null — never copy example or placeholder text

Text:
{text}
"""

    def _merge_enrichment(self, base: dict, extra: dict) -> dict:
        """Merge multipass enricher results — keep all entities, dedupe only."""
        materials_by_key: dict[str, MaterialDTO] = {}
        for mat in base.get("materials") or []:
            key = canonical_entity_key(mat.name) or mat.name.lower().strip()
            if key:
                materials_by_key[key] = mat
        for mat in extra.get("materials") or []:
            key = canonical_entity_key(mat.name) or mat.name.lower().strip()
            if not key:
                continue
            if key in materials_by_key:
                materials_by_key[key] = materials_by_key[key].merge_with(mat)
            else:
                materials_by_key[key] = mat

        processes_by_key: dict[str, dict] = {}
        for proc in (base.get("processes") or []) + (extra.get("processes") or []):
            key = str(proc.get("canonical_key") or proc.get("name") or "").lower().strip()
            if key and key not in processes_by_key:
                processes_by_key[key] = proc

        def _merge_named(items_a: list, items_b: list, key_field: str = "name") -> list:
            seen: set[str] = set()
            out: list = []
            for item in items_a + items_b:
                if not isinstance(item, dict):
                    continue
                key = str(item.get(key_field) or "").lower().strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append(item)
            return out

        teams_by_id: dict[str, dict] = {}
        for team in (base.get("teams") or []) + (extra.get("teams") or []):
            tid = str(team.get("id") or team.get("name") or "").strip()
            if tid:
                teams_by_id[tid] = team

        experts_by_id: dict[str, dict] = {}
        for expert in (base.get("experts") or []) + (extra.get("experts") or []):
            eid = str(expert.get("id") or expert.get("name") or "").strip()
            if eid:
                experts_by_id[eid] = expert

        experiments_by_id: dict[str, ExperimentDTO] = {}
        for exp in (base.get("experiments") or []) + (extra.get("experiments") or []):
            experiments_by_id[str(exp.id)] = exp

        topics: list[str] = []
        for topic in (base.get("topics") or []) + (extra.get("topics") or []):
            t = str(topic).strip()
            if t and t not in topics:
                topics.append(t)

        geo = dict(base.get("geography") or {})
        for key, val in (extra.get("geography") or {}).items():
            if val and not geo.get(key):
                geo[key] = val

        link_keys: set[tuple[str, str]] = set()
        merged_links: list[dict] = []
        for link in (base.get("material_process_links") or []) + (
            extra.get("material_process_links") or []
        ):
            mat_name = str(link.get("material_name") or "").lower().strip()
            proc_id = str(link.get("process_id") or link.get("process_name") or "").lower()
            token = (mat_name, proc_id)
            if mat_name and proc_id and token not in link_keys:
                link_keys.add(token)
                merged_links.append(link)

        materials = list(materials_by_key.values())
        processes = list(processes_by_key.values())
        return {
            "materials": materials,
            "experiments": list(experiments_by_id.values()),
            "topics": topics,
            "teams": list(teams_by_id.values()),
            "processes": processes,
            "equipment": _merge_named(base.get("equipment") or [], extra.get("equipment") or []),
            "facilities": _merge_named(base.get("facilities") or [], extra.get("facilities") or []),
            "experts": list(experts_by_id.values()),
            "geography": geo,
            "reliability": base.get("reliability") or extra.get("reliability"),
            "material_process_links": build_material_process_links(
                materials, processes, ""
            ) or merged_links,
        }

    def _parse_geography(self, raw: dict) -> dict:
        country_raw = str(raw.get("country") or "").strip()
        country = country_raw or None
        if country and is_llm_template_string(country):
            country = None
        scope_raw = str(raw.get("scope") or "").lower().strip()
        scope = scope_raw if scope_raw in ("domestic", "international", "global") else None
        return {"country": country, "scope": scope}

    def _parse_materials(
        self,
        raw_entities: list,
        document_id: UUID,
        target_lang: str,
    ) -> list[MaterialDTO]:
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
                display = pick_monolingual_label(name, target_lang)
                if not display or not is_valid_material_name(display):
                    logger.debug("Skipping invalid material name (class label): %s", display)
                    continue
                if is_llm_template_string(display):
                    logger.debug("Skipping template material name: %s", display)
                    continue
                key = canonical_entity_key(display)
                if not key or key in seen:
                    continue
                seen.add(key)
                mat_class = coerce_material_class(mat_class_raw, name=name)
                state = coerce_material_state(
                    item.get("state") if isinstance(item, dict) else None
                )
                materials.append(
                    MaterialDTO(
                        id=uuid4(),
                        name=display,
                        aliases=aliases,
                        material_class=mat_class,
                        state=state,
                        properties={},
                        source_document_id=document_id,
                    )
                )
        return materials

    def _reclassify_mislabeled_entities(self, raw: dict) -> dict:
        """Move section headings / process labels wrongly placed in experts[] to correct buckets."""
        if not isinstance(raw, dict):
            return raw

        processes = list(raw.get("processes") or [])
        facilities = list(raw.get("facilities") or [])
        equipment = list(raw.get("equipment") or [])
        kept_experts: list = []

        def item_name(item) -> str:
            if isinstance(item, dict):
                return str(item.get("name") or "").strip()
            return str(item or "").strip()

        for item in raw.get("experts") or []:
            name = item_name(item)
            if not name or is_llm_template_string(name):
                continue
            if looks_like_author_name(name) and not looks_like_section_heading(name):
                kept_experts.append(item)
                continue

            lower = name.lower()
            facility_hints = (
                "plant", "mine", "smelter", "refinery", "laboratory", "site",
                "facility", "facilities", "bay", "works", "operation", "mmc",
                "завод", "рудник", "комбинат", "фабрика", "комплекс",
            )
            equipment_hints = (
                "equipment", "reactor", "pump", "filter", "tank", "cell",
                "autoclave", "crusher", "conveyor", "компрессор", "насос", "печь",
            )
            if any(h in lower for h in facility_hints):
                fac = item if isinstance(item, dict) else {"name": name}
                facilities.append({
                    "name": name,
                    "country": fac.get("country"),
                    "facility_type": fac.get("facility_type") or "site",
                })
            elif any(h in lower for h in equipment_hints):
                equipment.append(item if isinstance(item, dict) else {"name": name})
            else:
                processes.append(
                    item
                    if isinstance(item, dict)
                    else {"name": name, "aliases": [], "materials": []}
                )

        moved = len(raw.get("experts") or []) - len(kept_experts)
        if moved > 0:
            logger.info(
                "Reclassified %s mislabeled expert entries → processes/facilities/equipment",
                moved,
            )
        raw["experts"] = kept_experts
        raw["processes"] = processes
        raw["facilities"] = facilities
        raw["equipment"] = equipment
        return raw

    def _parse_processes(
        self,
        raw: list,
        document_id: UUID,
        target_lang: str,
    ) -> list[dict]:
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
                display = pick_monolingual_label(name, target_lang)
                key = canonical_entity_key(display)
                if not display or not key or key in seen:
                    continue
                if is_llm_template_string(display) or is_placeholder_process(display):
                    logger.debug("Skipping invalid process name: %s", display)
                    continue
                seen.add(key)
                proc_materials: list[str] = []
                if isinstance(item, dict):
                    for m in item.get("materials") or []:
                        mname = str(m).strip()
                        if mname and not is_llm_template_string(mname):
                            proc_materials.append(mname)
                processes.append({
                    "id": str(uuid4()),
                    "name": display,
                    "canonical_key": key,
                    "aliases": aliases,
                    "materials": proc_materials,
                    "document_id": str(document_id),
                })
        return processes

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
        return items

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
            "coral", "bay", "site", "operation", "facility", "project",
        )
        if any(h in lower for h in facility_hints):
            return False
        # Allow short proper-noun site names (e.g. "Coral Bay")
        if name[:1].isupper() and any(c.isupper() for c in name[1:]):
            return False
        if re.match(r"^[a-z]+(?:\s+[a-z]+)+$", lower) and len(lower.split()) == 2:
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

        return facilities

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
        return looks_like_author_name(name)

    def _looks_like_org_name(self, name: str) -> bool:
        from ingestion.parsers.title_slide_extract import looks_like_organization_name

        if looks_like_affiliation_name(name):
            return True
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

    def _entity_name_blocklist(
        self,
        materials: list[MaterialDTO],
        processes: list[dict],
        equipment: list[dict],
        facilities: list[dict],
        teams: list[dict],
    ) -> set[str]:
        names: set[str] = set()
        for material in materials:
            names.add(material.name.lower())
            for alias in material.aliases or []:
                names.add(str(alias).lower())
        for proc in processes:
            names.add(str(proc.get("name") or "").lower())
            for alias in proc.get("aliases") or []:
                names.add(str(alias).lower())
            for mname in proc.get("materials") or []:
                names.add(str(mname).lower())
        for item in equipment:
            names.add(str(item.get("name") or "").lower())
        for fac in facilities:
            names.add(str(fac.get("name") or "").lower())
        for team in teams:
            names.add(str(team.get("name") or "").lower())
        return {n for n in names if n}

    def _is_strong_org_name(self, name: str) -> bool:
        """Only promote to team when affiliation signals are explicit."""
        from ingestion.parsers.title_slide_extract import looks_like_affiliation_name

        if looks_like_affiliation_name(name):
            return True
        cleaned = name.strip()
        if self._is_placeholder_team_name(cleaned):
            return False
        lower = cleaned.lower()
        if any(phrase in lower for phrase in _PROCESS_TOPIC_PHRASES):
            return False
        if is_placeholder_process(cleaned) or is_placeholder_equipment(cleaned):
            return False
        return False

    def _promote_org_to_team(
        self,
        teams: list[dict],
        name: str,
        document: DocumentDTO,
    ) -> None:
        """Reclassify mislabeled LLM expert entries that are actually organizations."""
        if not self._is_strong_org_name(name):
            return
        key = name.strip().lower()
        if any(str(t.get("name") or "").strip().lower() == key for t in teams):
            return
        teams.append({
            "id": str(uuid4()),
            "name": name.strip(),
            "members": self._split_person_names(document.authors),
        })

    def _should_reject_expert_name(self, name: str, blocklist: set[str]) -> bool:
        if looks_like_section_heading(name):
            return True
        if looks_like_affiliation_name(name) or self._is_strong_org_name(name):
            return True
        if is_blocklisted_entity_name(name, blocklist, exact=True):
            return True
        if any(phrase in name.lower() for phrase in _PROCESS_TOPIC_PHRASES):
            return True
        if is_placeholder_process(name) or is_placeholder_equipment(name):
            return True
        from ingestion.parsers.title_slide_extract import looks_like_job_title
        if looks_like_job_title(name):
            return True
        return False

    def _link_experts_to_team(self, experts: list[dict], teams: list[dict]) -> None:
        if not teams:
            return
        member_team: dict[str, str] = {}
        for team in teams:
            for member in team.get("members") or []:
                key = self._person_identity_key(str(member))
                if key:
                    member_team[key] = team["id"]
        for expert in experts:
            if expert.get("team_id"):
                continue
            key = self._person_identity_key(expert["name"])
            if key in member_team:
                expert["team_id"] = member_team[key]

    def _parse_experts(
        self,
        raw: list,
        teams: list[dict],
        document: DocumentDTO,
        extra_members: list[str] | None = None,
        blocklist: set[str] | None = None,
    ) -> list[dict]:
        experts: list[dict] = []
        seen: set[str] = set()
        blocklist = blocklist or set()

        def add_expert(
            name: str,
            field: str | None = None,
            *,
            from_llm: bool = False,
        ) -> None:
            cleaned = normalize_entity_name(normalize_person_name(name))
            if not cleaned or is_llm_template_string(cleaned):
                return
            if self._should_reject_expert_name(cleaned, blocklist):
                if self._is_strong_org_name(cleaned):
                    self._promote_org_to_team(teams, cleaned, document)
                else:
                    logger.debug("Rejected expert candidate: %s", cleaned)
                return
            if not self._looks_like_person(cleaned):
                logger.debug("Dropping non-person expert candidate: %s", cleaned)
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

        return experts

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
        working_materials = list(materials)
        if not working_materials and raw_findings:
            working_materials.append(
                MaterialDTO(
                    id=uuid4(),
                    name="process stream",
                    material_class=MaterialClass.OTHER,
                    state=MaterialState.SOLID,
                    properties={},
                    source_document_id=document_id,
                )
            )

        for item in raw_findings:
            if not isinstance(item, dict):
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
            topic = str(item.get("topic") or "").strip()
            label = title or summary

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
                for pname, pval in list(raw_params.items())[:12]:
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

            material_id = self._pick_material_for_finding(item, working_materials)
            if material_id is None and working_materials:
                material_id = working_materials[0].id
            if material_id is None:
                continue

            process_name = str(item.get("process") or topic or "").strip()
            linked_process_id = None
            if process_name:
                linked_process_id = (
                    process_by_name.get(process_name.lower())
                    or process_by_name.get(canonical_entity_key(process_name))
                )

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
        if working_materials and not materials:
            materials.extend(working_materials)
        return experiments, topics

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
            item_members = [
                m
                for m in self._split_person_names(item.get("members") or item.get("authors"))
                if self._looks_like_person(m)
            ]
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

        return teams

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
