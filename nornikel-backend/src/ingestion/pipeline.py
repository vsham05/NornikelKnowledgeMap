import logging
from pathlib import Path
import asyncio
import contextlib
from collections.abc import Callable

from domain.dto.document import DocumentDTO
from domain.dto.experiment import ExperimentDTO
from domain.dto.material import MaterialDTO
from domain.entity_glossary import canonical_entity_key
from ingestion.dedup import IngestResult, canonicalize_url, hash_document_text, hash_file_bytes
from ingestion.chunking import (
    build_extraction_batches,
    merge_chunks_for_embedding,
    stratified_document_text,
)
from infra.extraction_limits import resolve_extraction_max_chars
from ingestion.dedup_service import DocumentDedupService, cleanup_duplicate_documents
from ingestion.parsers.pdf_parser import PDFParser, peek_pdf_page_count
from ingestion.parsers.pdf_table_vlm import (
    collect_vlm_table_jobs,
    merge_table_into_chunk,
    render_region_from_file,
)
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
from infra.ingest_context import (
    reset_ingest_provider,
    reset_ingest_yandex_only,
    set_ingest_provider,
    set_ingest_yandex_only,
)
from infra.local_models import local_enricher_concurrency, local_extraction_concurrency, local_ingest_profile
from infra.llm_runtime import (
    LLMProvider,
    get_effective_llm_provider,
    get_llm_provider,
    get_local_model,
    get_yandex_model,
)
from ingestion.nlp.extraction_language import resolve_extraction_language

logger = logging.getLogger(__name__)

IngestProgressCallback = Callable[[float, str, dict | None], None]


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
            self.document_db.delete_document_images(document_id)
        except Exception as exc:
            logger.warning(f"MinIO image cleanup for {document_id}: {exc}")
        try:
            self.vector_db.delete_document_chunks(document_id)
        except Exception as exc:
            logger.warning(f"Vector cleanup for {document_id}: {exc}")
        try:
            self.graph_db.purge_orphan_entities()
        except Exception as exc:
            logger.warning(f"Orphan cleanup after purge {document_id}: {exc}")

    def _rollback_failed_ingest(self, document_id: str) -> None:
        """Clean partial graph/vector state when ingest aborts mid-pipeline."""
        logger.warning("Rolling back partial ingest for document %s", document_id)
        try:
            self.purge_document(document_id)
        except Exception as exc:
            logger.warning("Document rollback for %s: %s", document_id, exc)
        try:
            self.graph_db.purge_orphan_entities()
        except Exception as exc:
            logger.warning("Orphan cleanup after failed ingest: %s", exc)

    async def process_file(
        self,
        file_path: Path,
        original_filename: str | None = None,
        *,
        on_progress: IngestProgressCallback | None = None,
    ) -> IngestResult:
        suffix = file_path.suffix.lower()
        page_hint = (
            await asyncio.to_thread(peek_pdf_page_count, file_path)
            if suffix == ".pdf"
            else 0
        )
        early_route_meta: dict | None = None
        if page_hint > 0:
            ingest_provider, route_reason = self._resolve_ingest_provider(
                pages=page_hint,
                chunks=0,
            )
            effective_model = (
                get_yandex_model() if ingest_provider == "yandex" else get_local_model()
            )
            early_route_meta = {
                "llm_provider": ingest_provider,
                "llm_model": effective_model,
            }
            if on_progress:
                label = (
                    f"Yandex API · {effective_model}"
                    if ingest_provider == "yandex"
                    else f"Local · {effective_model}"
                )
                on_progress(
                    0.05,
                    f"Parsing {page_hint} pages — {label} ({route_reason})…",
                    early_route_meta,
                )
        elif on_progress:
            on_progress(0.05, "Parsing document…", None)

        def parse_progress(done: int, total: int) -> None:
            if not on_progress or total <= 0:
                return
            progress = 0.05 + (done / total) * 0.03
            meta = early_route_meta
            on_progress(progress, f"Parsing page {done}/{total}…", meta)

        file_hash = await asyncio.to_thread(hash_file_bytes, file_path)
        document = await asyncio.to_thread(
            self._parse_file,
            file_path,
            parse_progress if page_hint > 0 else None,
        )
        document.file_hash = file_hash
        document.file_path = original_filename or file_path.name
        document.content_hash = hash_document_text(document)

        decision = self.dedup.decide_for_file(file_hash, document, self.vector_db)
        if decision.action == "skip" and decision.existing_id:
            logger.info(f"Skipping duplicate file ingest: {decision.message}")
            return IngestResult(None, "skip", decision.existing_id, decision.message)

        if decision.action == "replace" and decision.existing_id:
            self.purge_document(decision.existing_id)

        try:
            await self._ingest_parsed_document(
                document,
                on_progress=on_progress,
                source_file=file_path,
            )
        except Exception:
            self._rollback_failed_ingest(str(document.id))
            raise
        action = "replace" if decision.action == "replace" else "create"
        return IngestResult(document, action, str(document.id), decision.message)

    async def ingest_url_document(
        self,
        document: DocumentDTO,
        source_url: str,
        *,
        on_progress: IngestProgressCallback | None = None,
    ) -> IngestResult:
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

        try:
            await self._ingest_parsed_document(
                document,
                on_progress=on_progress,
                source_file=file_path,
            )
        except Exception:
            self._rollback_failed_ingest(str(document.id))
            raise
        action = "replace" if decision.action == "replace" else "create"
        return IngestResult(document, action, str(document.id), decision.message)

    async def _ingest_parsed_document(
        self,
        document: DocumentDTO,
        *,
        on_progress: IngestProgressCallback | None = None,
        source_file: Path | None = None,
    ) -> None:
        ingest_provider, route_reason = self._resolve_ingest_provider(document)
        provider_token = set_ingest_provider(ingest_provider)
        yandex_token = None
        if ingest_provider == "yandex":
            yandex_token = set_ingest_yandex_only(True)
        effective_model = (
            get_yandex_model() if ingest_provider == "yandex" else get_local_model()
        )
        logger.info("Ingest LLM route: %s — %s", ingest_provider, route_reason)

        route_meta = {"llm_provider": ingest_provider, "llm_model": effective_model}

        def report(progress: float, message: str) -> None:
            if on_progress:
                on_progress(progress, message, route_meta)

        if on_progress:
            label = (
                f"Yandex API · {effective_model}"
                if ingest_provider == "yandex"
                else f"Local · {effective_model}"
            )
            on_progress(
                0.08,
                f"{label} — {route_reason}",
                route_meta,
            )

        try:
            await self._run_ingest_stages(
                document,
                on_progress=on_progress,
                report=report,
                route_reason=route_reason,
                route_meta=route_meta,
                effective_provider=ingest_provider,
                effective_model=effective_model,
                source_file=source_file,
            )
        finally:
            if yandex_token is not None:
                reset_ingest_yandex_only(yandex_token)
            reset_ingest_provider(provider_token)

    def _resolve_ingest_provider(
        self,
        document: DocumentDTO | None = None,
        *,
        pages: int | None = None,
        chunks: int | None = None,
    ) -> tuple[LLMProvider, str]:
        """Pick local 7B for short PDFs, Yandex API for long ones (hybrid mode)."""
        if not self.settings.ingest_hybrid_routing:
            provider = get_llm_provider()
            return provider, f"global provider ({provider})"

        if pages is None:
            pages = self._page_count(document) if document else 0
        if chunks is None:
            chunks = len(document.chunks) if document else 0
        max_pages = self.settings.ingest_local_max_pages
        yandex_ready = bool(self.settings.yandex_api_key and self.settings.yandex_folder_id)

        is_long = (
            pages > max_pages
            or (pages == 0 and chunks > max_pages)
            or chunks > max_pages * 2
        )
        if is_long:
            if yandex_ready:
                return (
                    "yandex",
                    f"long document ({pages} pages, {chunks} chunks > {max_pages} page local limit)",
                )
            logger.warning(
                "Long document (%s pages, %s chunks) but Yandex not configured; using local LLM",
                pages,
                chunks,
            )
            return (
                "local",
                f"long document ({pages} pages; Yandex unavailable)",
            )

        return "local", f"short document ({pages} pages ≤ {max_pages})"

    async def _run_ingest_stages(
        self,
        document: DocumentDTO,
        *,
        on_progress: IngestProgressCallback | None,
        report: Callable[[float, str], None],
        route_reason: str = "",
        route_meta: dict | None = None,
        effective_provider: str = "local",
        effective_model: str = "",
        source_file: Path | None = None,
    ) -> None:
        page_count = self._page_count(document)
        fast = self._use_fast_ingest(document)
        effective = get_effective_llm_provider()
        logger.info(
            "Ingesting document: %s (%s chunks, %s pages, fast=%s, llm=%s)",
            document.title,
            len(document.chunks),
            page_count,
            fast,
            effective,
        )

        await self._enrich_image_table_chunks(document, source_file, report=report)
        await self._analyze_images(document)

        batch_cap = self._resolve_extraction_batch_cap(fast, page_count)
        profile = local_ingest_profile(get_local_model()) if effective == "local" else {}
        logger.info(
            "Parallel ingest (%s): enricher + %s extraction batches (target <%s min)",
            "long doc" if fast else "standard",
            batch_cap,
            self.settings.ingest_target_max_minutes,
        )
        hybrid = self.settings.ingest_hybrid_routing and get_llm_provider() != effective
        hybrid_tag = "Hybrid · " if hybrid else ""
        if effective == "yandex":
            report(
                0.10,
                f"{hybrid_tag}Yandex API · {get_yandex_model()} — {route_reason or 'parallel extraction'}…",
            )
        else:
            tier = profile.get("tier", "light")
            parity = int(float(profile.get("yandex_char_parity", 0)) * 100)
            report(
                0.10,
                f"{hybrid_tag}Local LLM · {get_local_model()} ({tier}, ~{parity}% Yandex context) — "
                f"{route_reason or 'extraction'}…",
            )
        report(0.12, f"Extracting in parallel ({batch_cap} sections + knowledge map)…")
        all_materials, all_experiments, enrichment = await self._parallel_extract_and_enrich(
            document,
            fast_mode=fast,
            extraction_batches=batch_cap,
            on_progress=on_progress,
            route_meta=route_meta,
            effective_provider=effective_provider,
            effective_model=effective_model,
        )

        report(0.50, "Linking materials and experiments…")
        resolved_materials = await self._resolve_materials(all_materials)
        resolved_experiments = self._link_experiments_to_materials(
            all_experiments, all_materials, resolved_materials
        )

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
        report(0.72, "Saving figures and enrichment links…")
        await self._persist_figures(document)
        self._save_enrichment(document, enrichment, resolved_materials)
        self._link_enriched_experiments(resolved_experiments)
        report(0.82, "Building search embeddings…")
        await self._save_to_vector_db(document, fast_mode=fast)
        cleanup_duplicate_documents(self.graph_db, self.vector_db)
        try:
            self.graph_db.reconcile_duplicate_entities()
        except Exception as exc:
            logger.warning("Entity dedupe after ingest skipped: %s", exc)
        report(1.0, "Ingestion complete")
        logger.info(f"Ingestion completed: {document.id}")

    async def _parallel_extract_and_enrich(
        self,
        document: DocumentDTO,
        *,
        fast_mode: bool,
        extraction_batches: int,
        on_progress: IngestProgressCallback | None = None,
        route_meta: dict | None = None,
        effective_provider: str = "local",
        effective_model: str = "",
    ) -> tuple[list[MaterialDTO], list[ExperimentDTO], dict]:
        """Run enricher + entity extractor concurrently (same strategy for local & Yandex)."""
        enrich_done = False
        extract_done = False
        extract_completed = 0
        extract_total = 0
        api_label = (
            f"Yandex API · {effective_model}"
            if effective_provider == "yandex"
            else f"Local · {effective_model}"
        )

        def emit(progress: float, message: str) -> None:
            if on_progress:
                on_progress(progress, message, route_meta)

        async def heartbeat() -> None:
            tick = 0
            while not (enrich_done and extract_done):
                await asyncio.sleep(12)
                if enrich_done and extract_done:
                    break
                tick += 1
                waiting: list[str] = []
                if not enrich_done:
                    waiting.append("knowledge map")
                if not extract_done:
                    waiting.append(
                        f"entities ({extract_completed}/{extract_total})"
                        if extract_total
                        else "entities"
                    )
                # Heartbeat spans 36–49%; real progress jumps to 50% when both finish
                bump = min(0.13, tick * 0.015)
                emit(
                    0.36 + bump,
                    f"{api_label} — {' + '.join(waiting)} (still running)…",
                )

        async def run_enrich() -> dict:
            nonlocal enrich_done
            emit(0.14, f"{api_label} — building knowledge map…")
            # multipass=0 → enricher auto-computes passes to cover the full document
            result = await self.document_enricher.enrich_document(
                document,
                fast_mode=fast_mode,
                multipass=0,
            )
            enrich_done = True
            if extract_done:
                emit(0.50, f"{api_label} — knowledge map ready")
            else:
                emit(
                    0.44,
                    f"{api_label} — knowledge map ready — finishing entity extraction…",
                )
            return result

        async def run_extract() -> tuple[list[MaterialDTO], list[ExperimentDTO]]:
            nonlocal extract_done, extract_completed, extract_total
            try:
                return await self._extract_entities(
                    document,
                    max_batches=extraction_batches,
                    on_progress=on_progress,
                    progress_range=(0.16, 0.36),
                    fast_mode=fast_mode,
                    route_meta=route_meta,
                    api_label=api_label,
                    batch_state=_set_extract_counts,
                )
            finally:
                extract_done = True

        def _set_extract_counts(done: int, total: int) -> None:
            nonlocal extract_completed, extract_total
            extract_completed = done
            extract_total = total
            if done >= total and not enrich_done:
                emit(
                    0.38,
                    f"{api_label} — entities ({done}/{total}) done — finishing knowledge map…",
                )

        hb = asyncio.create_task(heartbeat())
        try:
            enrichment, (materials, experiments) = await asyncio.gather(
                run_enrich(),
                run_extract(),
            )
        finally:
            hb.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await hb
        emit(0.50, f"{api_label} — extraction complete")
        return materials, experiments, enrichment

    def _document_content_language(self, document: DocumentDTO) -> str:
        parts = [document.title or ""]
        for chunk in document.chunks[:24]:
            if chunk.text and chunk.text.strip():
                parts.append(chunk.text)
        sample = "\n".join(parts)
        return resolve_extraction_language(sample, self.settings.extraction_language)

    @staticmethod
    def _page_count(document: DocumentDTO) -> int:
        if not document.chunks:
            return 0
        return max((c.page_number or 0) for c in document.chunks)

    def _use_fast_ingest(self, document: DocumentDTO) -> bool:
        threshold = self.settings.ingest_fast_page_threshold
        pages = self._page_count(document)
        return pages >= threshold or len(document.chunks) >= threshold

    def _resolve_extraction_batch_cap(self, fast: bool, pages: int = 0) -> int:
        """Cap parallel LLM batches — long Yandex ingest must never run one call per page."""
        if get_effective_llm_provider() == "yandex":
            cap = self.settings.ingest_parallel_extraction_batches
            if pages >= 35:
                cap = min(24, max(cap, pages // 15))
            return cap

        # 0 = no batch thinning (local full-coverage mode only)
        if self.settings.llm_extraction_max_batches <= 0:
            if self.settings.ingest_local_full_coverage:
                return 0
            return 0
        if not fast:
            cap = min(4, self.settings.llm_extraction_max_batches)
        else:
            profile = local_ingest_profile(get_local_model())
            tier_batches = int(profile.get("extraction_batches") or 0)
            cap = max(self.settings.ingest_parallel_extraction_batches, tier_batches or 0)
            if tier_batches <= 0:
                return 0
        if pages >= 35 and self.settings.llm_extraction_max_batches > 0:
            scaled = max(cap, pages // 18)
            cap = min(self.settings.llm_extraction_max_batches, scaled)
        return cap

    async def enrich_existing_document(
        self, document_id: str, *, force: bool = False
    ) -> dict:
        """Backfill graph entities for a document already in Neo4j."""
        if not force and self.graph_db.document_has_entities(document_id):
            return {"document_id": document_id, "status": "skipped", "reason": "already_enriched"}

        document = self.graph_db.load_document_dto(document_id)
        if not document:
            return {"document_id": document_id, "status": "not_found"}

        ingest_provider, route_reason = self._resolve_ingest_provider(document)
        provider_token = set_ingest_provider(ingest_provider)
        yandex_token = None
        if ingest_provider == "yandex":
            yandex_token = set_ingest_yandex_only(True)
        logger.info("Enrich LLM route: %s — %s", ingest_provider, route_reason)

        try:
            enrichment = await self.document_enricher.enrich_document(document)
        finally:
            if yandex_token is not None:
                reset_ingest_yandex_only(yandex_token)
            reset_ingest_provider(provider_token)

        self.graph_db.delete_document_enrichment_people(document_id)
        self.graph_db.delete_document_topics(document_id)
        self.graph_db.save_document(
            document, content_language=self._document_content_language(document)
        )
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

    def _parse_file(
        self,
        file_path: Path,
        on_page_progress: Callable[[int, int], None] | None = None,
    ) -> DocumentDTO:
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            return self.pdf_parser.parse(file_path, on_page_progress=on_page_progress)
        if suffix == ".docx":
            return self.docx_parser.parse(file_path)
        raise ValueError(f"Unsupported file type: {suffix}")

    async def _upload_files(self, document: DocumentDTO, original_file_path: Path):
        self.document_db.upload_file(
            original_file_path,
            f"documents/{document.id}/{original_file_path.name}",
        )

    async def _extract_entities(
        self,
        document: DocumentDTO,
        *,
        max_batches: int | None = None,
        on_progress: IngestProgressCallback | None = None,
        progress_range: tuple[float, float] = (0.12, 0.48),
        fast_mode: bool = False,
        route_meta: dict | None = None,
        api_label: str = "",
        batch_state: Callable[[int, int], None] | None = None,
    ) -> tuple[list[MaterialDTO], list[ExperimentDTO]]:
        """Extract materials/experiments with batched LLM calls for long documents."""
        p_start, p_end = progress_range
        max_chars = resolve_extraction_max_chars(self.settings)
        batch_limit = (
            max_batches
            if max_batches is not None
            else self.settings.llm_extraction_max_batches
        )
        batches = build_extraction_batches(
            document.chunks,
            max_text_chars=max_chars,
            max_batches=batch_limit,
        )
        if not batches:
            return [], []

        if len(batches) == 1 and len(batches[0]) == 1:
            result = await self.entity_extractor.extract_from_text(
                batches[0][0].text,
                document.id,
                batches[0][0].page_number,
                fast_mode=fast_mode,
            )
            return result["materials"], result["experiments"]

        logger.info(
            "Fast extraction: %s page chunks → %s LLM batch(es) (cap=%s)",
            len(document.chunks),
            len(batches),
            batch_limit,
        )

        sem = asyncio.Semaphore(
            min(self.settings.ingest_llm_concurrency, 8)
            if get_effective_llm_provider() == "yandex"
            else local_extraction_concurrency(
                get_local_model(),
                configured=self.settings.ingest_llm_concurrency,
            )
        )
        completed = 0
        total_batches = len(batches)
        label = api_label or "LLM"

        async def run_batch(batch: list) -> dict:
            nonlocal completed
            async with sem:
                parts: list[str] = []
                for c in batch:
                    if not c.text or not c.text.strip():
                        continue
                    page = c.page_number
                    header = f"[page {page}]\n" if page else ""
                    parts.append(f"{header}{c.text.strip()}")
                text = "\n\n".join(parts)
                page = batch[0].page_number
                result = await self.entity_extractor.extract_from_text(
                    text, document.id, page, fast_mode=fast_mode
                )
                completed += 1
                if batch_state:
                    batch_state(completed, total_batches)
                if on_progress:
                    frac = completed / max(total_batches, 1)
                    progress = p_start + (p_end - p_start) * frac
                    on_progress(
                        progress,
                        f"{label} — extracting entities ({completed}/{total_batches})…",
                        route_meta,
                    )
                return result

        results = await asyncio.gather(*(run_batch(batch) for batch in batches))
        materials: list[MaterialDTO] = []
        experiments: list[ExperimentDTO] = []
        for result in results:
            materials.extend(result.get("materials") or [])
            experiments.extend(result.get("experiments") or [])
        return materials, experiments

    async def _persist_figures(self, document: DocumentDTO) -> None:
        """Upload figure bytes to MinIO and create FigureGallery graph blob."""
        payloads: list[tuple] = []
        if hasattr(self.pdf_parser, "last_image_payloads"):
            payloads = list(self.pdf_parser.last_image_payloads or [])

        if not payloads and not document.images:
            return

        doc_id = str(document.id)
        for image, data, ext in payloads:
            try:
                key = self.document_db.upload_image_bytes(doc_id, str(image.id), data, ext)
                image.file_path = key
            except Exception as exc:
                logger.warning("Failed to store image %s: %s", image.id, exc)

        stored = [img for img in document.images if img.file_path]
        if stored:
            self.graph_db.save_figure_gallery(doc_id, stored)
            logger.info("Saved figure gallery: %s images for document %s", len(stored), doc_id)

    async def _enrich_image_table_chunks(
        self,
        document: DocumentDTO,
        source_file: Path | None,
        *,
        report: Callable[[float, str], None] | None = None,
    ) -> int:
        """OCR image-based tables via vision model and merge into page chunks."""
        if not self.settings.ingest_table_vlm or not source_file:
            return 0
        path = Path(source_file)
        if path.suffix.lower() != ".pdf" or not path.is_file():
            return 0

        jobs = await asyncio.to_thread(
            collect_vlm_table_jobs,
            path,
            document,
            max_jobs=self.settings.ingest_table_vlm_max,
        )
        if not jobs:
            return 0

        if report:
            report(
                0.09,
                f"Vision OCR: {len(jobs)} image table(s) via {self.settings.vlm_model}…",
            )

        sem = asyncio.Semaphore(2)

        async def run_job(job: dict) -> tuple[int, str, str] | None:
            async with sem:
                try:
                    png = await asyncio.to_thread(
                        render_region_from_file,
                        path,
                        job["page_number"],
                        job["region"],
                    )
                    markdown = await self.vlm_analyzer.extract_table_markdown(
                        png,
                        job["title"],
                    )
                    if markdown:
                        return job["chunk_index"], job["title"], markdown
                except Exception as exc:
                    logger.warning(
                        "Image table OCR failed p%s %r: %s",
                        job.get("page_number"),
                        (job.get("title") or "")[:50],
                        exc,
                    )
                return None

        results = await asyncio.gather(*(run_job(job) for job in jobs))
        enriched = 0
        for result in results:
            if not result:
                continue
            chunk_index, title, markdown = result
            chunk = document.chunks[chunk_index]
            chunk.text = merge_table_into_chunk(chunk.text or "", title, markdown)
            enriched += 1

        if enriched:
            document.content_hash = hash_document_text(document)
            logger.info(
                "VLM table OCR merged %s table(s) into chunks (%s)",
                enriched,
                self.settings.vlm_model,
            )
        return enriched

    async def _analyze_images(self, document: DocumentDTO):
        if not document.images:
            return
        logger.debug("Skipping general figure VLM for %s image(s)", len(document.images))

    async def _resolve_materials(self, materials: list[MaterialDTO]) -> dict[str, MaterialDTO]:
        resolved: dict[str, MaterialDTO] = {}
        for material in materials:
            key = canonical_entity_key(material.name) or material.name.lower().strip()
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
            resolved_id = self.graph_db.save_process(
                proc["id"],
                proc["name"],
                doc_id,
                proc.get("aliases"),
                proc.get("canonical_key"),
            )
            proc["id"] = resolved_id

        team_id_remap: dict[str, str] = {}
        for team in enrichment.get("teams") or []:
            old_id = team["id"]
            resolved_id = self.graph_db.save_team(
                team_id=old_id,
                name=team["name"],
                members=team.get("members") or [],
                document_id=doc_id,
            )
            team["id"] = resolved_id
            team_id_remap[old_id] = resolved_id

        for fac in enrichment.get("facilities") or []:
            self.graph_db.save_facility(
                fac["id"],
                fac["name"],
                fac.get("country"),
                doc_id,
                fac.get("facility_type"),
            )

        for expert in enrichment.get("experts") or []:
            team_id = expert.get("team_id")
            if team_id and team_id in team_id_remap:
                team_id = team_id_remap[team_id]
            resolved_id = self.graph_db.save_expert(
                expert["id"],
                expert["name"],
                expert.get("field"),
                doc_id,
                team_id,
            )
            expert["id"] = resolved_id

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
        self.graph_db.save_document(
            document, content_language=self._document_content_language(document)
        )
        for material in materials.values():
            self.graph_db.save_material(material)
            self.graph_db.link_document_material(str(document.id), str(material.id))
        for experiment in experiments:
            self.graph_db.save_experiment(experiment)
        logger.info(
            f"Saved to graph: document + {len(materials)} materials, {len(experiments)} experiments"
        )

    async def _save_to_vector_db(self, document: DocumentDTO, *, fast_mode: bool = False):
        max_chunks = self.settings.ingest_embed_max_chunks
        if max_chunks <= 0:
            max_chunks = 10_000
        chunks_with_text = merge_chunks_for_embedding(
            document.chunks,
            max_chunks=max_chunks,
        )
        chunks_with_text = [c for c in chunks_with_text if c.text and c.text.strip()]
        if not chunks_with_text:
            logger.info("No text chunks to embed")
            return
        try:
            batch_size = 32 if fast_mode else 24
            embed_batches = [
                chunks_with_text[start : start + batch_size]
                for start in range(0, len(chunks_with_text), batch_size)
            ]

            async def embed_one(batch: list) -> None:
                texts = [c.text for c in batch]
                embeddings = await self.embedding_client.embed_texts(texts)
                for chunk, embedding in zip(batch, embeddings):
                    self.vector_db.save_text_chunk(chunk, embedding)

            await asyncio.gather(*(embed_one(batch) for batch in embed_batches))
            logger.info(
                "Saved to vector DB: %s chunks with embeddings (from %s pages)",
                len(chunks_with_text),
                len(document.chunks),
            )
        except Exception as exc:
            logger.error(f"Vector DB save failed (document still saved to graph): {exc}")
