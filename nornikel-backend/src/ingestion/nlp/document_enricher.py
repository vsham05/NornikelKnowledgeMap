"""Extract knowledge-graph entities for mining & metallurgy R&D documents."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from domain.dto.document import DocumentDTO
from domain.dto.experiment import ExperimentDTO, RegimeDTO, RegimeParameterDTO
from domain.dto.material import MaterialDTO
from domain.dto.property_value import PropertyValueDTO
from domain.enums import DOCUMENT_RELIABILITY, DocumentType, MaterialClass, MaterialState, RegimeType
from infra.llm_client import LLMClient
from settings import Settings

logger = logging.getLogger(__name__)

_SAMPLE_CHARS = 14_000


class DocumentEnricher:
    """One LLM pass per document → full R&D knowledge map entities."""

    def __init__(self, settings: Settings):
        self.llm_client = LLMClient(settings)

    async def enrich_document(self, document: DocumentDTO) -> dict:
        text = self._sample_text(document)
        if len(text.strip()) < 80:
            return self._empty()

        prompt = self._build_prompt(document.title, text)
        try:
            raw = await self.llm_client.chat_json(user_message=prompt, temperature=0.1)
        except Exception as exc:
            logger.warning("Document enricher LLM failed: %s", exc)
            return self._from_authors_only(document)

        geography = self._parse_geography(raw.get("geography") or {})
        materials = self._parse_materials(raw.get("materials") or raw.get("entities") or [], document.id)
        processes = self._parse_processes(raw.get("processes") or [], document.id)
        equipment = self._parse_named_list(raw.get("equipment") or [], "equipment")
        facilities = self._parse_facilities(raw.get("facilities") or [])
        teams = self._parse_teams(raw.get("teams") or [], document)
        experts = self._parse_experts(raw.get("experts") or [], teams)
        topics = [str(t).strip() for t in (raw.get("topics") or []) if str(t).strip()]

        if not materials:
            materials = [
                MaterialDTO(
                    id=uuid4(),
                    name=document.title[:120] or "Document subject",
                    material_class=MaterialClass.OTHER,
                    state=MaterialState.SOLID,
                    source_document_id=document.id,
                )
            ]

        primary_process = processes[0]["id"] if processes else None
        experiments, extra_topics = self._parse_findings(
            raw.get("findings") or [],
            document.id,
            materials[0].id,
            primary_process,
        )
        for topic in extra_topics:
            if topic not in topics:
                topics.append(topic)
        if not topics and document.title:
            topics = [document.title[:60]]

        reliability = DOCUMENT_RELIABILITY.get(
            document.document_type.value,
            DOCUMENT_RELIABILITY[DocumentType.OTHER.value],
        )

        logger.info(
            "Enricher: %s mat, %s exp, %s proc, %s eq, %s fac, %s teams",
            len(materials), len(experiments), len(processes),
            len(equipment), len(facilities), len(teams),
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

    def _build_prompt(self, title: str, text: str) -> str:
        return f"""Analyze this mining/metallurgy R&D document and extract a knowledge graph as JSON.
Domain: hydrometallurgy, pyrometallurgy, electrowinning, leaching, flotation, ecology, waste recycling.
Russian or English text.

Title: {title}

Return ONLY valid JSON:
{{
  "geography": {{"country": "Russia|China|…", "scope": "domestic|international|global"}},
  "materials": [{{"name": "nickel sulfate|copper matte|…", "aliases": []}}],
  "processes": [{{"name": "electrowinning|heap leaching|flash smelting", "aliases": []}}],
  "equipment": [{{"name": "diaphragm cell|electroextraction bath|PVD furnace"}}],
  "facilities": [{{"name": "plant or laboratory", "country": "…"}}],
  "experts": [{{"name": "person name", "field": "hydrometallurgy|…"}}],
  "findings": [
    {{
      "title": "short label",
      "topic": "process or theme",
      "process": "linked process name if any",
      "summary": "one grounded sentence",
      "status": "completed|ongoing|planned",
      "parameters": {{"flow_rate": {{"value": 12, "unit": "L/min", "min": null, "max": null}}}}
    }}
  ],
  "topics": ["catholyte circulation", "mine water treatment"],
  "teams": [{{"name": "lab or company", "members": ["author1"]}}]
}}

Rules:
- materials: substances, ores, products (Ni, Cu, gypsum, catholyte…)
- processes: technological operations (not generic words)
- findings: 1-6 experiments, results, or confirmed conclusions with numeric parameters when present
- geography.scope: domestic for Russia/CIS internal practice, international for foreign-only, global for worldwide review
- Ground everything in the document text

Text:
{text}
"""

    def _parse_geography(self, raw: dict) -> dict:
        country = str(raw.get("country") or "").strip() or None
        scope = str(raw.get("scope") or "global").lower().strip()
        if scope not in ("domestic", "international", "global"):
            scope = "global"
        return {"country": country, "scope": scope}

    def _parse_materials(self, raw_entities: list, document_id: UUID) -> list[MaterialDTO]:
        materials: list[MaterialDTO] = []
        seen: set[str] = set()
        for item in raw_entities:
            if not isinstance(item, dict):
                name = str(item).strip()
                aliases: list[str] = []
            else:
                name = str(item.get("name") or "").strip()
                aliases = [str(a) for a in item.get("aliases") or [] if a]
            if not name or len(name) < 2:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            materials.append(
                MaterialDTO(
                    id=uuid4(),
                    name=name,
                    aliases=aliases,
                    material_class=MaterialClass.OTHER,
                    state=MaterialState.SOLID,
                    properties={},
                    source_document_id=document_id,
                )
            )
        return materials[:10]

    def _parse_processes(self, raw: list, document_id: UUID) -> list[dict]:
        processes: list[dict] = []
        seen: set[str] = set()
        for item in raw:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                aliases = [str(a) for a in item.get("aliases") or [] if a]
            else:
                name = str(item).strip()
                aliases = []
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            processes.append({
                "id": str(uuid4()),
                "name": name,
                "aliases": aliases,
                "document_id": str(document_id),
            })
        return processes[:8]

    def _parse_named_list(self, raw: list, kind: str) -> list[dict]:
        items: list[dict] = []
        seen: set[str] = set()
        for item in raw:
            name = str(item.get("name") if isinstance(item, dict) else item).strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            items.append({"id": str(uuid4()), "name": name, "kind": kind})
        return items[:8]

    def _parse_facilities(self, raw: list) -> list[dict]:
        facilities: list[dict] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            facilities.append({
                "id": str(uuid4()),
                "name": name,
                "country": str(item.get("country") or "").strip() or None,
            })
        return facilities[:6]

    def _parse_experts(self, raw: list, teams: list[dict]) -> list[dict]:
        experts: list[dict] = []
        seen: set[str] = set()
        team_id = teams[0]["id"] if teams else None
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            experts.append({
                "id": str(uuid4()),
                "name": name,
                "field": str(item.get("field") or "").strip() or None,
                "team_id": team_id,
            })
        return experts[:10]

    def _parse_findings(
        self,
        raw_findings: list,
        document_id: UUID,
        material_id: UUID,
        process_id: str | None,
    ) -> tuple[list[ExperimentDTO], list[str]]:
        experiments: list[ExperimentDTO] = []
        topics: list[str] = []

        for item in raw_findings:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("summary") or "").strip()
            if not title:
                continue
            topic = str(item.get("topic") or item.get("process") or "general").strip()
            if topic and topic not in topics:
                topics.append(topic)
            status = str(item.get("status") or "completed").lower()
            if status not in ("completed", "ongoing", "planned"):
                status = "completed"

            params: dict[str, RegimeParameterDTO] = {
                "status": RegimeParameterDTO(
                    name="status",
                    value=PropertyValueDTO(value=status, unit=""),
                )
            }
            raw_params = item.get("parameters") or {}
            if isinstance(raw_params, dict):
                for pname, pval in list(raw_params.items())[:6]:
                    if not isinstance(pval, dict):
                        continue
                    params[str(pname)] = RegimeParameterDTO(
                        name=str(pname),
                        value=PropertyValueDTO(
                            value=str(pval.get("value", "")),
                            unit=str(pval.get("unit") or ""),
                            value_min=pval.get("min"),
                            value_max=pval.get("max"),
                        ),
                    )

            exp = ExperimentDTO(
                id=uuid4(),
                material_id=material_id,
                regime=RegimeDTO(
                    regime_type=RegimeType.OTHER,
                    name=topic[:80] if topic else "finding",
                    parameters=params,
                    description=str(item.get("summary") or title)[:500],
                ),
                conclusions=[str(item.get("summary") or title)[:500]],
                document_id=document_id,
            )
            if process_id:
                exp.__dict__["_process_id"] = process_id
            experiments.append(exp)
        return experiments[:10], topics[:12]

    def _parse_teams(self, raw_teams: list, document: DocumentDTO) -> list[dict]:
        teams: list[dict] = []
        seen: set[str] = set()

        for author in document.authors or []:
            name = str(author).strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                teams.append({"id": str(uuid4()), "name": name, "members": [name]})

        for item in raw_teams:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            members = [str(m).strip() for m in item.get("members") or [] if m]
            teams.append({"id": str(uuid4()), "name": name, "members": members or [name]})
        return teams[:8]

    def _from_authors_only(self, document: DocumentDTO) -> dict:
        subject = MaterialDTO(
            id=uuid4(),
            name=document.title[:120] or "Document",
            material_class=MaterialClass.OTHER,
            state=MaterialState.SOLID,
            source_document_id=document.id,
        )
        teams = self._parse_teams([], document)
        return {
            "materials": [subject],
            "experiments": [],
            "topics": ["general"],
            "teams": teams,
            "processes": [],
            "equipment": [],
            "facilities": [],
            "experts": [],
            "geography": {"country": None, "scope": "global"},
            "reliability": DOCUMENT_RELIABILITY.get(
                document.document_type.value, 0.7
            ),
        }

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
            "geography": {"country": None, "scope": "global"},
            "reliability": 0.7,
        }
