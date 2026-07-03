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
from ingestion.nlp.material_process_linker import build_material_process_links
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

        # Always run document enricher so graph shows full ontology per README:
        # publication → material → process → experiment → property + experts/teams
        enrichment = await self.document_enricher.enrich_document(document)
        enrich_resolved = await self._resolve_materials(enrichment["materials"])
        for mat_id, mat in enrich_resolved.items():
            if mat_id in resolved_materials:
                resolved_materials[mat_id] = resolved_materials[mat_id].merge_with(mat)
            else:
                resolved_materials[mat_id] = mat

        enrich_experiments = self._link_experiments_to_materials(
            enrichment["experiments"],
            enrichment["materials"],
            resolved_materials,
        )
        seen_exp_ids = {str(e.id) for e in resolved_experiments}
        for exp in enrich_experiments:
            if str(exp.id) not in seen_exp_ids:
                resolved_experiments.append(exp)
                seen_exp_ids.add(str(exp.id))

        self._save_to_graph(resolved_materials, resolved_experiments, document)
        self._save_enrichment(document, enrichment, resolved_materials)
        self._link_enriched_experiments(resolved_experiments)
        await self._save_to_vector_db(document)
        cleanup_duplicate_documents(self.graph_db, self.vector_db)
        logger.info(f"Ingestion completed: {document.id}")

    async def enrich_existing_document(
        self, document_id: str, *, force: bool = False
    ) -> dict:
        """Backfill graph entities for a document already in Neo4j."""
        if not force and self.graph_db.document_has_entities(document_id):
            return {"document_id": document_id, "status": "skipped", "reason": "already_enriched"}

        document = self.graph_db.load_document_dto(document_id)
        if not document:
            return {"document_id": document_id, "status": "not_found"}

        enrichment = await self.document_enricher.enrich_document(document)
        self.graph_db.delete_document_enrichment_people(document_id)
        self.graph_db.delete_document_topics(document_id)
        self.graph_db.save_document(document)
        resolved_materials = await self._resolve_materials(enrichment["materials"])
        resolved_experiments = self._link_experiments_to_materials(
            enrichment["experiments"],
            enrichment["materials"],
            resolved_materials,
        )
        for material in resolved_materials.values():
            self.graph_db.save_material(material)
            self.graph_db.link_document_material(document_id, str(material.id))
        for experiment in resolved_experiments:
            self.graph_db.save_experiment(experiment)
        self._save_enrichment(document, enrichment, resolved_materials)
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
            results.append(await self.enrich_existing_document(doc_id, force=True))
        enriched = sum(1 for r in results if r.get("status") == "enriched")
        linked = self.graph_db.backfill_material_document_links()
        process_links = self.backfill_material_process_links()
        return {
            "processed": len(results),
            "enriched": enriched,
            "material_links": linked,
            "material_process_links": process_links,
            "results": results,
        }

    def backfill_material_process_links(
        self, document_id: str | None = None
    ) -> dict:
        """Rebuild Material-[:PROCESSED_IN]->Process for document(s) without LLM."""
        if document_id:
            doc_ids = [document_id]
        else:
            doc_ids = [
                str(d.get("id") or "")
                for d in self.graph_db.list_documents(limit=200)
                if d.get("id")
            ]

        results: list[dict] = []
        total_links = 0
        for doc_id in doc_ids:
            document = self.graph_db.load_document_dto(doc_id)
            if not document:
                results.append({"document_id": doc_id, "status": "not_found"})
                continue

            materials = self.graph_db.list_material_dtos_for_document(doc_id)
            with self.graph_db.driver.session() as session:
                processes = [
                    dict(r)
                    for r in session.run(
                        """
                        MATCH (d:Document {id: $id})-[:DESCRIBES_PROCESS]->(p:Process)
                        RETURN p.id AS id, p.name AS name,
                               coalesce(p.aliases, []) AS aliases
                        """,
                        {"id": doc_id},
                    )
                ]

            if not materials:
                results.append({"document_id": doc_id, "status": "no_materials"})
                continue
            if not processes:
                results.append({"document_id": doc_id, "status": "no_processes"})
                continue

            sample = self.document_enricher._sample_text(document)
            links = build_material_process_links(materials, processes, sample)
            self.graph_db.delete_document_material_process_links(doc_id)

            name_to_id: dict[str, str] = {}
            for mat in materials:
                name_to_id[mat.name.lower()] = str(mat.id)
                for alias in mat.aliases or []:
                    name_to_id[str(alias).lower()] = str(mat.id)

            proc_by_name = {
                str(p["name"]).strip().lower(): str(p["id"]) for p in processes
            }
            created = 0
            linked_names: set[str] = set()
            for link in links:
                mat_name = str(link.get("material_name") or "").strip().lower()
                proc_id = link.get("process_id")
                if not proc_id:
                    proc_name = str(link.get("process_name") or "").strip().lower()
                    proc_id = proc_by_name.get(proc_name)
                mat_id = name_to_id.get(mat_name)
                if mat_id and proc_id:
                    self.graph_db.link_material_process(mat_id, str(proc_id))
                    created += 1
                    linked_names.add(mat_name)

            orphans = [
                m.name for m in materials if m.name.lower() not in linked_names
            ]
            total_links += created
            results.append({
                "document_id": doc_id,
                "status": "backfilled",
                "materials": len(materials),
                "links_created": created,
                "orphan_materials": orphans,
            })

        return {"documents": len(results), "links_created": total_links, "results": results}

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
        resolved: dict[str, MaterialDTO] = {}
        for material in materials:
            key = material.name.lower().strip()
            resolved_id = await self.entity_resolver.resolve_material(material)
            if resolved_id != material.id:
                existing = self.graph_db.get_material_by_id(resolved_id)
                if existing:
                    material = existing.merge_with(material)
                else:
                    material = material.model_copy(update={"id": resolved_id})

            if key in resolved:
                resolved[key] = resolved[key].merge_with(material)
            else:
                resolved[key] = material
        return resolved

    def _material_key(self, name: str) -> str:
        return name.lower().strip()

    def _link_experiments_to_materials(
        self,
        experiments: list[ExperimentDTO],
        raw_materials: list[MaterialDTO],
        resolved_materials: dict[str, MaterialDTO],
    ) -> list[ExperimentDTO]:
        linked = []
        name_to_id = {
            self._material_key(raw_mat.name): resolved_materials[self._material_key(raw_mat.name)].id
            for raw_mat in raw_materials
            if self._material_key(raw_mat.name) in resolved_materials
        }
        for exp in experiments:
            material_name = getattr(exp, "_material_name", None)
            mat_key = self._material_key(material_name) if material_name else ""
            if mat_key and mat_key in name_to_id:
                linked.append(exp.model_copy(update={"material_id": name_to_id[mat_key]}))
            elif exp.material_id:
                linked.append(exp)
            else:
                logger.warning(f"Could not link experiment to material: {material_name}")
        return linked

    def _save_enrichment(
        self,
        document: DocumentDTO,
        enrichment: dict,
        resolved_materials: dict | None = None,
    ) -> None:
        doc_id = str(document.id)
        self.graph_db.delete_document_enrichment_people(doc_id)
        self.graph_db.delete_document_material_process_links(doc_id)
        geo = enrichment.get("geography") or {}
        self.graph_db.update_document_metadata(
            doc_id,
            country=geo.get("country"),
            scope=geo.get("scope"),
            reliability=enrichment.get("reliability"),
            domain="mining_metallurgy",
        )

        for proc in enrichment.get("processes") or []:
            self.graph_db.save_process(
                proc["id"], proc["name"], doc_id, proc.get("aliases")
            )

        for team in enrichment.get("teams") or []:
            self.graph_db.save_team(
                team_id=team["id"],
                name=team["name"],
                members=team.get("members") or [],
                document_id=doc_id,
            )

        for fac in enrichment.get("facilities") or []:
            self.graph_db.save_facility(
                fac["id"],
                fac["name"],
                fac.get("country"),
                doc_id,
                fac.get("facility_type"),
            )

        for expert in enrichment.get("experts") or []:
            self.graph_db.save_expert(
                expert["id"],
                expert["name"],
                expert.get("field"),
                doc_id,
                expert.get("team_id"),
            )

        for eq in enrichment.get("equipment") or []:
            self.graph_db.save_equipment(
                eq["id"], eq["name"], doc_id, None
            )

        name_to_id: dict[str, str] = {}
        if resolved_materials:
            for material in resolved_materials.values():
                name_to_id[material.name.lower()] = str(material.id)
                for alias in material.aliases:
                    name_to_id[str(alias).lower()] = str(material.id)

        all_doc_materials = self.graph_db.list_material_dtos_for_document(doc_id)
        for material in all_doc_materials:
            name_to_id[material.name.lower()] = str(material.id)
            for alias in material.aliases or []:
                name_to_id[str(alias).lower()] = str(material.id)

        processes = enrichment.get("processes") or []
        proc_id_by_name: dict[str, str] = {}
        for proc in processes:
            pname = str(proc.get("name") or "").strip().lower()
            if pname:
                proc_id_by_name[pname] = str(proc["id"])

        links = enrichment.get("material_process_links") or []
        if all_doc_materials and processes:
            sample = self.document_enricher._sample_text(document)
            links = build_material_process_links(all_doc_materials, processes, sample)

        for link in links:
            mat_name = str(link.get("material_name") or "").strip().lower()
            proc_id = link.get("process_id")
            proc_name = str(link.get("process_name") or "").strip().lower()
            mat_id = name_to_id.get(mat_name)
            if not proc_id and proc_name:
                proc_id = proc_id_by_name.get(proc_name)
            if mat_id and proc_id:
                self.graph_db.link_material_process(mat_id, str(proc_id))

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
            self.graph_db.link_document_material(str(document.id), str(material.id))
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
