"""Extract knowledge-graph entities from any document (not only materials science)."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from domain.dto.document import DocumentDTO
from domain.dto.experiment import ExperimentDTO, RegimeDTO, RegimeParameterDTO
from domain.dto.material import MaterialDTO
from domain.dto.property_value import PropertyValueDTO
from domain.enums import MaterialClass, MaterialState, RegimeType
from infra.llm_client import LLMClient
from settings import Settings

logger = logging.getLogger(__name__)

_SAMPLE_CHARS = 12_000


class DocumentEnricher:
    """One LLM pass per document → materials, experiments, topics, teams."""

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

        materials = self._parse_materials(raw.get("entities") or [], document.id)
        teams = self._parse_teams(raw.get("teams") or [], document)
        topics = [
            str(t).strip()
            for t in (raw.get("topics") or [])
            if str(t).strip()
        ]

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

        experiments, extra_topics = self._parse_findings(
            raw.get("findings") or [],
            document.id,
            materials[0].id,
        )
        for topic in extra_topics:
            if topic not in topics:
                topics.append(topic)

        if not topics and document.title:
            topics = [document.title[:60]]

        logger.info(
            "Document enricher: %s materials, %s experiments, %s topics, %s teams",
            len(materials),
            len(experiments),
            len(topics),
            len(teams),
        )
        return {
            "materials": materials,
            "experiments": experiments,
            "topics": topics,
            "teams": teams,
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
        return f"""Analyze this document and extract a small knowledge graph as JSON.
Works for scientific papers, reports, news, and essays (Russian or English).

Document title: {title}

Return ONLY valid JSON:
{{
  "entities": [
    {{"name": "main subject / organization / person / material / concept", "aliases": []}}
  ],
  "findings": [
    {{
      "title": "short label for a key claim, event, or result",
      "topic": "theme or category",
      "year": null,
      "summary": "one sentence grounded in the text",
      "status": "completed|ongoing|planned"
    }}
  ],
  "topics": ["theme1", "theme2"],
  "teams": [
    {{"name": "author group or institution", "members": ["person1", "person2"]}}
  ]
}}

Rules:
- entities: 2-6 important named subjects from the document
- findings: 1-5 key claims, events, or results (experiments, studies, historical events)
- topics: 2-5 thematic tags (these become "modes" in the graph)
- teams: authors, research groups, institutions, or organizations mentioned
- Use empty arrays only if truly nothing applies
- Ground everything in the document text

Text:
{text}
"""

    def _parse_materials(self, raw_entities: list, document_id: UUID) -> list[MaterialDTO]:
        materials: list[MaterialDTO] = []
        seen: set[str] = set()
        for item in raw_entities:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
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
                    aliases=[str(a) for a in item.get("aliases") or [] if a],
                    material_class=MaterialClass.OTHER,
                    state=MaterialState.SOLID,
                    properties={},
                    source_document_id=document_id,
                )
            )
        return materials[:8]

    def _parse_findings(
        self,
        raw_findings: list,
        document_id: UUID,
        material_id: UUID,
    ) -> tuple[list[ExperimentDTO], list[str]]:
        experiments: list[ExperimentDTO] = []
        topics: list[str] = []

        for item in raw_findings:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("summary") or "").strip()
            if not title:
                continue
            topic = str(item.get("topic") or "general").strip()
            if topic and topic not in topics:
                topics.append(topic)
            status = str(item.get("status") or "completed").lower()
            if status not in ("completed", "ongoing", "planned"):
                status = "completed"

            regime_name = topic[:80] if topic else "finding"
            experiments.append(
                ExperimentDTO(
                    id=uuid4(),
                    material_id=material_id,
                    regime=RegimeDTO(
                        regime_type=RegimeType.OTHER,
                        name=regime_name,
                        parameters={
                            "status": RegimeParameterDTO(
                                name="status",
                                value=PropertyValueDTO(value=status, unit=""),
                            )
                        },
                        description=str(item.get("summary") or title)[:500],
                    ),
                    conclusions=[str(item.get("summary") or title)[:500]],
                    document_id=document_id,
                )
            )
        return experiments[:8], topics[:10]

    def _parse_teams(self, raw_teams: list, document: DocumentDTO) -> list[dict]:
        teams: list[dict] = []
        seen: set[str] = set()

        for author in document.authors or []:
            name = str(author).strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                teams.append({
                    "id": str(uuid4()),
                    "name": name,
                    "members": [name],
                })

        for item in raw_teams:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            members = [str(m).strip() for m in item.get("members") or [] if m]
            teams.append({
                "id": str(uuid4()),
                "name": name,
                "members": members or [name],
            })
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
        topics = ["general"]
        if document.year:
            topics.append(str(document.year))
        return {
            "materials": [subject],
            "experiments": [],
            "topics": topics,
            "teams": teams,
        }

    def _empty(self) -> dict:
        return {"materials": [], "experiments": [], "topics": [], "teams": []}
