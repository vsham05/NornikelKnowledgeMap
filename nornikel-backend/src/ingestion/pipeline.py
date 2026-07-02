import logging
from pathlib import Path

from domain.dto.document import DocumentDTO
from domain.dto.experiment import ExperimentDTO
from domain.dto.material import MaterialDTO
from ingestion.dedup import IngestResult, canonicalize_url, hash_document_text, hash_file_bytes
from ingestion.dedup_service import DocumentDedupService, cleanup_duplicate_documents
from ingestion.parsers.pdf_parser import PDFParser
from ingestion.parsers.docx_parser import DOCXParser
from ingestion.vision.vlm_analyzer import VLMAnalyzer
from ingestion.nlp.document_enricher import DocumentEnricher
from ingestion.nlp.entity_extractor import EntityExtractor
from ingestion.nlp.entity_resolver import EntityResolver
from storage.graph_db import GraphDB
from storage.vector_db import VectorDB
from storage.document_db import DocumentDB
from settings import Settings

from infra.embedding_client import EmbeddingClient

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """Ingest documents into Neo4j + Qdrant with deduplication."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.pdf_parser = PDFParser()
        self.docx_parser = DOCXParser()
        self.vlm_analyzer = VLMAnalyzer(settings)
        self.entity_extractor = EntityExtractor(settings)
        self.document_enricher = DocumentEnricher(settings)
        self.graph_db = GraphDB(settings)
        self.entity_resolver = EntityResolver(self.graph_db)
        self.vector_db = VectorDB(settings)
        self.document_db = DocumentDB(settings)
        self.embedding_client = EmbeddingClient(settings)
        self.dedup = DocumentDedupService(self.graph_db)

    def purge_document(self, document_id: str) -> None:
        self.graph_db.delete_document(document_id)
        try:
            self.vector_db.delete_document_chunks(document_id)
        except Exception as exc:
            logger.warning(f"Vector cleanup for {document_id}: {exc}")

    async def process_file(
        self,
        file_path: Path,
        original_filename: str | None = None,
    ) -> IngestResult:
        file_hash = hash_file_bytes(file_path)
        document = self._parse_file(file_path)
        document.file_hash = file_hash
        document.file_path = original_filename or file_path.name
        document.content_hash = hash_document_text(document)

        decision = self.dedup.decide_for_file(file_hash, document, self.vector_db)
        if decision.action == "skip" and decision.existing_id:
            logger.info(f"Skipping duplicate file ingest: {decision.message}")
            return IngestResult(None, "skip", decision.existing_id, decision.message)

        if decision.action == "replace" and decision.existing_id:
            self.purge_document(decision.existing_id)

        await self._ingest_parsed_document(document)
        action = "replace" if decision.action == "replace" else "create"
        return IngestResult(document, action, str(document.id), decision.message)

    async def ingest_url_document(self, document: DocumentDTO, source_url: str) -> IngestResult:
        canonical = canonicalize_url(source_url)
        document.canonical_source = canonical
        document.file_path = canonical
        document.content_hash = hash_document_text(document)

        decision = self.dedup.decide_for_url(canonical, document, self.vector_db)
        if decision.action == "skip" and decision.existing_id:
            logger.info(f"Skipping duplicate URL ingest: {decision.message}")
            return IngestResult(None, "skip", decision.existing_id, decision.message)

        if decision.action == "replace" and decision.existing_id:
            self.purge_document(decision.existing_id)

        await self._ingest_parsed_document(document)
        action = "replace" if decision.action == "replace" else "create"
        return IngestResult(document, action, str(document.id), decision.message)

    async def _ingest_parsed_document(self, document: DocumentDTO) -> None:
        logger.info(f"Ingesting document: {document.title} ({len(document.chunks)} chunks)")

        await self._analyze_images(document)

        all_materials: list[MaterialDTO] = []
        all_experiments: list[ExperimentDTO] = []

        for chunk in document.chunks:
            extraction_result = await self.entity_extractor.extract_from_text(
                chunk.text,
                document.id,
                chunk.page_number,
            )
            all_materials.extend(extraction_result["materials"])
            all_experiments.extend(extraction_result["experiments"])

        resolved_materials = await self._resolve_materials(all_materials)
        resolved_experiments = self._link_experiments_to_materials(
            all_experiments, all_materials, resolved_materials
        )

        enrichment = None
        if not resolved_materials and not resolved_experiments:
            enrichment = await self.document_enricher.enrich_document(document)
            resolved_materials = await self._resolve_materials(enrichment["materials"])
            resolved_experiments = self._link_experiments_to_materials(
                enrichment["experiments"],
                enrichment["materials"],
                resolved_materials,
            )

        self._save_to_graph(resolved_materials, resolved_experiments, document)
        if enrichment:
            self._save_enrichment(document, enrichment)
            self._link_enriched_experiments(resolved_experiments)
        await self._save_to_vector_db(document)
        cleanup_duplicate_documents(self.graph_db, self.vector_db)
        logger.info(f"Ingestion completed: {document.id}")

    async def enrich_existing_document(self, document_id: str) -> dict:
        """Backfill graph entities for a document already in Neo4j."""
        if self.graph_db.document_has_entities(document_id):
            return {"document_id": document_id, "status": "skipped", "reason": "already_enriched"}

        document = self.graph_db.load_document_dto(document_id)
        if not document:
            return {"document_id": document_id, "status": "not_found"}

        enrichment = await self.document_enricher.enrich_document(document)
        resolved_materials = await self._resolve_materials(enrichment["materials"])
        resolved_experiments = self._link_experiments_to_materials(
            enrichment["experiments"],
            enrichment["materials"],
            resolved_materials,
        )
        for material in resolved_materials.values():
            self.graph_db.save_material(material)
        for experiment in resolved_experiments:
            self.graph_db.save_experiment(experiment)
        self._save_enrichment(document, enrichment)
        self._link_enriched_experiments(resolved_experiments)

        return {
            "document_id": document_id,
            "status": "enriched",
            "materials": len(resolved_materials),
            "experiments": len(resolved_experiments),
            "teams": len(enrichment.get("teams") or []),
            "topics": len(enrichment.get("topics") or []),
        }

    async def enrich_all_documents(self) -> dict:
        docs = self.graph_db.list_documents(limit=200)
        results = []
        for doc in docs:
            doc_id = str(doc.get("id") or "")
            if not doc_id:
                continue
            results.append(await self.enrich_existing_document(doc_id))
        enriched = sum(1 for r in results if r.get("status") == "enriched")
        return {"processed": len(results), "enriched": enriched, "results": results}

    def _parse_file(self, file_path: Path) -> DocumentDTO:
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            return self.pdf_parser.parse(file_path)
        if suffix == ".docx":
            return self.docx_parser.parse(file_path)
        raise ValueError(f"Unsupported file type: {suffix}")

    async def _upload_files(self, document: DocumentDTO, original_file_path: Path):
        self.document_db.upload_file(
            original_file_path,
            f"documents/{document.id}/{original_file_path.name}",
        )

    async def _analyze_images(self, document: DocumentDTO):
        if not document.images:
            return
        logger.info(f"Skipping VLM analysis for {len(document.images)} image(s)")

    async def _resolve_materials(self, materials: list[MaterialDTO]) -> dict[str, MaterialDTO]:
        resolved = {}
        for material in materials:
            resolved_id = await self.entity_resolver.resolve_material(material)
            if resolved_id != material.id:
                existing = self.graph_db.get_material_by_id(resolved_id)
                if existing:
                    merged = existing.merge_with(material)
                    self.graph_db.update_material(merged)
                    resolved[material.name] = merged
            else:
                resolved[material.name] = material
        return resolved

    def _link_experiments_to_materials(
        self,
        experiments: list[ExperimentDTO],
        raw_materials: list[MaterialDTO],
        resolved_materials: dict[str, MaterialDTO],
    ) -> list[ExperimentDTO]:
        linked = []
        name_to_id = {
            raw_mat.name: resolved_materials[raw_mat.name].id
            for raw_mat in raw_materials
            if raw_mat.name in resolved_materials
        }
        for exp in experiments:
            material_name = getattr(exp, "_material_name", None)
            if material_name and material_name in name_to_id:
                linked.append(exp.model_copy(update={"material_id": name_to_id[material_name]}))
            elif exp.material_id:
                linked.append(exp)
            else:
                logger.warning(f"Could not link experiment to material: {material_name}")
        return linked

    def _save_enrichment(self, document: DocumentDTO, enrichment: dict) -> None:
        doc_id = str(document.id)
        geo = enrichment.get("geography") or {}
        self.graph_db.update_document_metadata(
            doc_id,
            country=geo.get("country"),
            scope=geo.get("scope"),
            reliability=enrichment.get("reliability"),
            domain="mining_metallurgy",
        )

        process_by_name = {}
        for proc in enrichment.get("processes") or []:
            self.graph_db.save_process(
                proc["id"], proc["name"], doc_id, proc.get("aliases")
            )
            process_by_name[proc["name"].lower()] = proc["id"]

        for team in enrichment.get("teams") or []:
            self.graph_db.save_team(
                team_id=team["id"],
                name=team["name"],
                members=team.get("members") or [],
                document_id=doc_id,
            )

        facility_ids = []
        for fac in enrichment.get("facilities") or []:
            self.graph_db.save_facility(
                fac["id"], fac["name"], fac.get("country"), doc_id
            )
            facility_ids.append(fac["id"])

        if enrichment.get("teams") and facility_ids:
            self.graph_db.link_team_facility(
                enrichment["teams"][0]["id"], facility_ids[0]
            )

        for expert in enrichment.get("experts") or []:
            self.graph_db.save_expert(
                expert["id"],
                expert["name"],
                expert.get("field"),
                doc_id,
                expert.get("team_id"),
            )

        primary_process_id = (
            enrichment["processes"][0]["id"] if enrichment.get("processes") else None
        )
        for eq in enrichment.get("equipment") or []:
            self.graph_db.save_equipment(
                eq["id"], eq["name"], doc_id, primary_process_id
            )

        for topic in enrichment.get("topics") or []:
            self.graph_db.link_document_topic(doc_id, topic)

    def _link_enriched_experiments(self, experiments: list[ExperimentDTO]) -> None:
        for exp in experiments:
            process_id = getattr(exp, "_process_id", None)
            if process_id:
                self.graph_db.link_experiment_process(str(exp.id), process_id)

    def _save_to_graph(
        self,
        materials: dict[str, MaterialDTO],
        experiments: list[ExperimentDTO],
        document: DocumentDTO,
    ):
        self.graph_db.save_document(document)
        for material in materials.values():
            self.graph_db.save_material(material)
        for experiment in experiments:
            self.graph_db.save_experiment(experiment)
        logger.info(
            f"Saved to graph: document + {len(materials)} materials, {len(experiments)} experiments"
        )

    async def _save_to_vector_db(self, document: DocumentDTO):
        chunks_with_text = [c for c in document.chunks if c.text and c.text.strip()]
        if not chunks_with_text:
            logger.info("No text chunks to embed")
            return
        try:
            texts = [c.text for c in chunks_with_text]
            embeddings = await self.embedding_client.embed_texts(texts)
            for chunk, embedding in zip(chunks_with_text, embeddings):
                self.vector_db.save_text_chunk(chunk, embedding)
            logger.info(f"Saved to vector DB: {len(chunks_with_text)} chunks with embeddings")
        except Exception as exc:
            logger.error(f"Vector DB save failed (document still saved to graph): {exc}")
