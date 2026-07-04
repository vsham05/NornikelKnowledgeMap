import logging
import json
from uuid import UUID

from neo4j import AsyncGraphDatabase, GraphDatabase

from domain.dto.material import MaterialDTO
from domain.material_taxonomy import coerce_material_class, get_material_taxonomy
from domain.dto.experiment import ExperimentDTO
from domain.dto.document import DocumentDTO, DocumentChunkDTO
from domain.enums import DOCUMENT_RELIABILITY, DocumentType
from domain.property_labels import property_display_label
from settings import Settings
from search.query_processing import extract_search_terms

logger = logging.getLogger(__name__)

VISUAL_NODE_LABELS = (
    "Document",
    "Material",
    "Experiment",
    "Team",
    "Process",
    "Equipment",
    "Facility",
    "Expert",
    "FigureGallery",
)
SKIP_VISUAL_REL_TYPES = frozenset({"HAS_CHUNK", "CONTAINS_IMAGE"})


def _neo4j_scalar(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [
            item if isinstance(item, (str, int, float, bool)) else str(item)
            for item in value
        ]
    return str(value)


def _neo4j_conditions(conditions: dict | None) -> str | None:
    """Neo4j node properties cannot be maps — store conditions as JSON text."""
    if not conditions:
        return None
    clean = {
        str(key): _neo4j_scalar(val)
        for key, val in conditions.items()
        if val is not None
    }
    if not clean:
        return None
    return json.dumps(clean, ensure_ascii=False)


class GraphDB:
    """Работа с Neo4j графовой БД."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password)
        )
        logger.info("Connected to Neo4j")
    
    def close(self):
        self.driver.close()

    @staticmethod
    def _visual_node_id(node) -> str | None:
        props = dict(node)
        labels = list(node.labels)
        if props.get("id"):
            return str(props["id"])
        if "RegimeParameter" in labels and props.get("name"):
            return f"rp:{props['name']}"
        if "Property" in labels and props.get("canonical_name"):
            return f"prop:{props['canonical_name']}"
        return None

    def _default_display_lang(self) -> str:
        configured = (self.settings.extraction_language or "auto").strip().lower()
        if configured in ("ru", "en"):
            return configured
        return "en"

    def _load_property_languages(
        self, session, property_names: set[str] | None = None
    ) -> dict[str, str]:
        """Map property canonical_name -> display language from linked documents."""
        if property_names:
            result = session.run(
                """
                MATCH (p:Property)<-[:MEASURED]-(e:Experiment)-[:DESCRIBED_IN]->(d:Document)
                WHERE p.canonical_name IN $names
                RETURN p.canonical_name AS name,
                       collect(DISTINCT d.content_language) AS langs
                """,
                {"names": list(property_names)},
            )
        else:
            result = session.run(
                """
                MATCH (p:Property)<-[:MEASURED]-(e:Experiment)-[:DESCRIBED_IN]->(d:Document)
                WHERE p.canonical_name IS NOT NULL
                RETURN p.canonical_name AS name,
                       collect(DISTINCT d.content_language) AS langs
                """
            )
        out: dict[str, str] = {}
        for row in result:
            langs = [lang for lang in (row.get("langs") or []) if lang in ("ru", "en")]
            if not langs:
                continue
            if len(langs) == 1:
                out[str(row["name"])] = langs[0]
            else:
                out[str(row["name"])] = "ru" if langs.count("ru") >= langs.count("en") else "en"
        return out

    def _lang_from_doc_langs(self, langs: list[str] | None) -> str:
        cleaned = [lang for lang in (langs or []) if lang in ("ru", "en")]
        if not cleaned:
            return self._default_display_lang()
        if len(cleaned) == 1:
            return cleaned[0]
        return "ru" if cleaned.count("ru") >= cleaned.count("en") else "en"

    def _resolve_property_lang(
        self, canonical_name: str | None, property_langs: dict[str, str] | None
    ) -> str:
        if canonical_name and property_langs and canonical_name in property_langs:
            return property_langs[canonical_name]
        return self._default_display_lang()

    def _visual_node_label(
        self,
        node,
        *,
        display_value: str | None = None,
        display_unit: str | None = None,
        property_langs: dict[str, str] | None = None,
    ) -> str:
        props = dict(node)
        labels = list(node.labels)
        if "Property" in labels and props.get("canonical_name"):
            canonical = str(props["canonical_name"])
            lang = self._resolve_property_lang(canonical, property_langs)
            base = property_display_label(canonical, lang=lang)
            if display_value:
                raw = str(display_value).strip()
                if raw.startswith("{") or raw.startswith("{'") or len(raw) > 48:
                    return base
                unit = (display_unit or props.get("unit") or "").strip()
                return f"{base}: {display_value}{(' ' + unit) if unit else ''}"
            return base
        return (
            props.get("title")
            or props.get("name")
            or props.get("canonical_name")
            or props.get("regime_name")
            or (str(props["id"])[:8] if props.get("id") else "Unknown")
        )

    def _get_graph_labels(self) -> set[str]:
        """Return labels present in the database (avoids Neo4j warnings on empty schema)."""
        with self.driver.session() as session:
            record = session.run(
                "CALL db.labels() YIELD label RETURN collect(label) AS labels"
            ).single()
            return set(record["labels"]) if record else set()

    def _get_relationship_types(self) -> set[str]:
        with self.driver.session() as session:
            record = session.run(
                "CALL db.relationshipTypes() YIELD relationshipType "
                "RETURN collect(relationshipType) AS types"
            ).single()
            return set(record["types"]) if record else set()
    
    # ================== WRITE ==================
    
    def save_material(self, material: MaterialDTO) -> str:
        """Сохраняет материал с динамическими свойствами. Returns resolved node id."""
        from domain.entity_glossary import canonical_entity_key as ckey

        taxonomy = get_material_taxonomy()
        material_stage = taxonomy.get_stage(material.material_class).value
        canonical_key = ckey(material.name) or material.name.lower().strip().replace(" ", "_")
        with self.driver.session() as session:
            record = session.run("""
                MERGE (m:Material {canonical_key: $canonical_key})
                ON CREATE SET m.id = $id,
                    m.name = $name,
                    m.material_class = $material_class,
                    m.material_stage = $material_stage,
                    m.state = $state,
                    m.aliases = $aliases,
                    m.microstructure_features = $microstructure_features,
                    m.source_document_id = $source_document_id,
                    m.created_at = $created_at
                ON MATCH SET m.name = $name,
                    m.material_class = $material_class,
                    m.material_stage = $material_stage,
                    m.state = $state,
                    m.aliases = [x IN coalesce(m.aliases, []) + $aliases WHERE x IS NOT NULL | x],
                    m.microstructure_features = coalesce(m.microstructure_features, $microstructure_features),
                    m.source_document_id = coalesce(m.source_document_id, $source_document_id)
                RETURN m.id AS id
            """, {
                "canonical_key": canonical_key,
                "id": str(material.id),
                "name": material.name,
                "material_class": material.material_class.value,
                "material_stage": material_stage,
                "state": material.state.value,
                "aliases": material.aliases,
                "microstructure_features": material.microstructure_features,
                "source_document_id": str(material.source_document_id) if material.source_document_id else None,
                "created_at": material.created_at.isoformat()
            }).single()
            mat_id = str(record["id"]) if record else str(material.id)

            for prop_name, prop in material.properties.items():
                session.run("""
                    MATCH (m:Material {id: $mat_id})
                    MERGE (p:Property {canonical_name: $name})
                    SET p.category = $category,
                        p.unit = $unit
                    MERGE (m)-[:HAS_PROPERTY]->(p)
                    
                    MERGE (v:PropertyValue {id: $val_id})
                    SET v.value = $value,
                        v.value_min = $value_min,
                        v.value_max = $value_max,
                        v.conditions = $conditions,
                        v.source_text = $source_text,
                        v.confidence = $confidence
                    MERGE (p)-[:HAS_VALUE]->(v)
                """, {
                    "mat_id": mat_id,
                    "name": prop_name,
                    "category": prop.category,
                    "unit": prop.value.unit,
                    "val_id": f"{mat_id}_{prop_name}",
                    "value": prop.value.value if not isinstance(prop.value.value, (dict, list)) else str(prop.value.value),
                    "value_min": prop.value.value_min,
                    "value_max": prop.value.value_max,
                    "conditions": _neo4j_conditions(prop.value.conditions),
                    "source_text": prop.value.source_text,
                    "confidence": prop.value.confidence
                })
        
        logger.info(f"Saved material: {material.name} ({len(material.properties)} properties)")
        if material.source_document_id:
            self.link_document_material(
                str(material.source_document_id),
                mat_id,
            )
        return mat_id

    def link_document_material(self, document_id: str, material_id: str) -> None:
        """Connect a material to its source publication (fixes orphan nodes in graph viz)."""
        with self.driver.session() as session:
            session.run("""
                MATCH (d:Document {id: $doc_id})
                MATCH (m:Material {id: $mat_id})
                MERGE (d)-[:MENTIONS_MATERIAL]->(m)
            """, {"doc_id": document_id, "mat_id": material_id})

    def save_experiment(self, experiment: ExperimentDTO) -> None:
        """Сохраняет эксперимент."""
        with self.driver.session() as session:
            # Создаем узел Experiment
            regime_type = experiment.regime.regime_type.value
            regime_name = experiment.regime.name or regime_type
            status = "completed"
            status_param = experiment.regime.parameters.get("status")
            if status_param and status_param.value.value:
                status = str(status_param.value.value)

            session.run("""
                MERGE (e:Experiment {id: $id})
                SET e.regime_type = $regime_type,
                    e.regime_name = $regime_name,
                    e.regime_description = $regime_description,
                    e.conclusions = $conclusions,
                    e.document_id = $document_id,
                    e.status = $status,
                    e.created_at = $created_at
            """, {
                "id": str(experiment.id),
                "regime_type": regime_type,
                "regime_name": regime_name,
                "regime_description": experiment.regime.description,
                "conclusions": experiment.conclusions,
                "document_id": str(experiment.document_id),
                "status": status,
                "created_at": experiment.created_at.isoformat()
            })
            
            # Связь с материалом
            session.run("""
                MATCH (e:Experiment {id: $exp_id})
                MATCH (m:Material {id: $mat_id})
                MERGE (e)-[:USES_MATERIAL]->(m)
            """, {"exp_id": str(experiment.id), "mat_id": str(experiment.material_id)})
            
            # Параметры режима как узлы
            for param_name, param in experiment.regime.parameters.items():
                session.run("""
                    MATCH (e:Experiment {id: $exp_id})
                    MERGE (rp:RegimeParameter {name: $name})
                    MERGE (e)-[:HAS_REGIME_PARAM {
                        value: $value,
                        unit: $unit
                    }]->(rp)
                """, {
                    "exp_id": str(experiment.id),
                    "name": param_name,
                    "value": str(param.value.value),
                    "unit": param.value.unit or ""
                })
            
            # Измеренные свойства
            for prop_name, prop in experiment.measured_properties.items():
                session.run("""
                    MATCH (e:Experiment {id: $exp_id})
                    MERGE (p:Property {canonical_name: $name})
                    SET p.category = $category
                    
                    MERGE (e)-[:MEASURED {
                        value: $value,
                        unit: $unit,
                        source_text: $source_text
                    }]->(p)
                """, {
                    "exp_id": str(experiment.id),
                    "name": prop_name,
                    "category": prop.category,
                    "value": str(prop.value.value),
                    "unit": prop.value.unit or "",
                    "source_text": prop.value.source_text or ""
                })
            
            # Связь с документом
            session.run("""
                MATCH (e:Experiment {id: $exp_id})
                MATCH (d:Document {id: $doc_id})
                MERGE (e)-[:DESCRIBED_IN]->(d)
            """, {"exp_id": str(experiment.id), "doc_id": str(experiment.document_id)})
        
        logger.info(f"Saved experiment: {experiment.id}")

    def save_team(
        self,
        team_id: str,
        name: str,
        members: list[str],
        document_id: str,
    ) -> str:
        from domain.entity_glossary import canonical_entity_key as ckey

        key = ckey(name) or name.lower().strip().replace(" ", "_")
        with self.driver.session() as session:
            record = session.run("""
                MERGE (t:Team {canonical_key: $key})
                ON CREATE SET t.id = $id,
                    t.name = $name,
                    t.members = $members,
                    t.canonical_key = $key
                ON MATCH SET t.name = $name,
                    t.members = [x IN coalesce(t.members, []) + $members WHERE x IS NOT NULL | x]
                WITH t
                MATCH (d:Document {id: $doc_id})
                MERGE (t)-[:AUTHORED]->(d)
                RETURN t.id AS id
            """, {
                "key": key,
                "id": team_id,
                "name": name,
                "members": members,
                "doc_id": document_id,
            }).single()
            resolved_id = str(record["id"]) if record else team_id
        logger.info("Saved team: %s", name)
        return resolved_id

    def link_document_topic(self, document_id: str, topic: str) -> None:
        topic = (topic or "").strip()[:120]
        if not topic:
            return
        with self.driver.session() as session:
            session.run("""
                MATCH (d:Document {id: $doc_id})
                MERGE (rp:RegimeParameter {name: $topic})
                MERGE (d)-[:HAS_TOPIC]->(rp)
            """, {"doc_id": document_id, "topic": topic})

    def update_document_metadata(
        self,
        document_id: str,
        *,
        country: str | None = None,
        scope: str | None = None,
        reliability: float | None = None,
        domain: str | None = None,
    ) -> None:
        with self.driver.session() as session:
            session.run("""
                MATCH (d:Document {id: $doc_id})
                SET d.country = coalesce($country, d.country),
                    d.scope = coalesce($scope, d.scope),
                    d.reliability = coalesce($reliability, d.reliability),
                    d.domain = coalesce($domain, d.domain),
                    d.updated_at = datetime()
            """, {
                "doc_id": document_id,
                "country": country,
                "scope": scope,
                "reliability": reliability,
                "domain": domain,
            })

    def save_process(self, process_id: str, name: str, document_id: str, aliases: list[str] | None = None, canonical_key: str | None = None) -> str:
        from domain.entity_glossary import canonical_entity_key as ckey
        key = canonical_key or ckey(name)
        with self.driver.session() as session:
            record = session.run("""
                MERGE (p:Process {canonical_key: $key})
                ON CREATE SET p.id = $id, p.name = $name, p.aliases = $aliases
                ON MATCH SET p.name = $name,
                    p.aliases = [x IN coalesce(p.aliases, []) + $aliases WHERE x IS NOT NULL | x]
                WITH p
                MATCH (d:Document {id: $doc_id})
                MERGE (d)-[:DESCRIBES_PROCESS]->(p)
                RETURN p.id AS id
            """, {
                "key": key,
                "id": process_id,
                "name": name,
                "aliases": aliases or [],
                "doc_id": document_id,
            }).single()
            return str(record["id"]) if record else process_id

    def save_equipment(
        self, equipment_id: str, name: str, document_id: str, process_id: str | None = None
    ) -> str:
        from domain.entity_glossary import canonical_entity_key as ckey

        key = ckey(name) or name.lower().strip().replace(" ", "_")
        with self.driver.session() as session:
            record = session.run("""
                MERGE (eq:Equipment {canonical_key: $key})
                ON CREATE SET eq.id = $id, eq.name = $name
                ON MATCH SET eq.name = $name
                WITH eq
                MATCH (d:Document {id: $doc_id})
                MERGE (d)-[:MENTIONS_EQUIPMENT]->(eq)
                RETURN eq.id AS id
            """, {"key": key, "id": equipment_id, "name": name, "doc_id": document_id}).single()
            resolved_id = str(record["id"]) if record else equipment_id
            if process_id:
                session.run("""
                    MATCH (eq:Equipment {id: $eq_id})
                    MATCH (p:Process {id: $proc_id})
                    MERGE (p)-[:USES_EQUIPMENT]->(eq)
                """, {"eq_id": resolved_id, "proc_id": process_id})
        return resolved_id

    def save_facility(
        self,
        facility_id: str,
        name: str,
        country: str | None,
        document_id: str,
        facility_type: str | None = None,
    ) -> str:
        from domain.entity_glossary import canonical_entity_key as ckey

        key = ckey(name) or name.lower().strip().replace(" ", "_")
        with self.driver.session() as session:
            record = session.run("""
                MERGE (f:Facility {canonical_key: $key})
                ON CREATE SET f.id = $id,
                    f.name = $name,
                    f.country = $country,
                    f.facility_type = $facility_type
                ON MATCH SET f.name = $name,
                    f.country = coalesce($country, f.country),
                    f.facility_type = coalesce($facility_type, f.facility_type)
                WITH f
                MATCH (d:Document {id: $doc_id})
                MERGE (d)-[:FROM_FACILITY]->(f)
                RETURN f.id AS id
            """, {
                "key": key,
                "id": facility_id,
                "name": name,
                "country": country,
                "facility_type": facility_type,
                "doc_id": document_id,
            }).single()
            return str(record["id"]) if record else facility_id

    def save_expert(
        self,
        expert_id: str,
        name: str,
        field: str | None,
        document_id: str,
        team_id: str | None = None,
    ) -> str:
        from domain.entity_glossary import canonical_entity_key as ckey

        key = ckey(name) or name.lower().strip().replace(" ", "_")
        with self.driver.session() as session:
            record = session.run("""
                MERGE (x:Expert {canonical_key: $key})
                ON CREATE SET x.id = $id,
                    x.name = $name,
                    x.field = $field,
                    x.canonical_key = $key
                ON MATCH SET x.name = $name,
                    x.field = coalesce($field, x.field)
                WITH x
                MATCH (d:Document {id: $doc_id})
                MERGE (d)-[:AUTHORED_BY]->(x)
                RETURN x.id AS id
            """, {
                "key": key,
                "id": expert_id,
                "name": name,
                "field": field,
                "doc_id": document_id,
            }).single()
            resolved_id = str(record["id"]) if record else expert_id
            if team_id:
                session.run("""
                    MATCH (x:Expert {id: $expert_id})
                    MATCH (t:Team {id: $team_id})
                    MERGE (x)-[:MEMBER_OF]->(t)
                """, {"expert_id": resolved_id, "team_id": team_id})
        return resolved_id

    def link_team_facility(self, team_id: str, facility_id: str) -> None:
        with self.driver.session() as session:
            session.run("""
                MATCH (t:Team {id: $team_id})
                MATCH (f:Facility {id: $facility_id})
                MERGE (t)-[:WORKS_AT]->(f)
            """, {"team_id": team_id, "facility_id": facility_id})

    def link_experiment_process(self, experiment_id: str, process_id: str) -> None:
        with self.driver.session() as session:
            session.run("""
                MATCH (e:Experiment {id: $exp_id})
                MATCH (p:Process {id: $proc_id})
                MERGE (e)-[:USES_PROCESS]->(p)
            """, {"exp_id": experiment_id, "proc_id": process_id})

    def link_material_process(self, material_id: str, process_id: str) -> None:
        with self.driver.session() as session:
            session.run("""
                MATCH (m:Material {id: $mat_id})
                MATCH (p:Process {id: $proc_id})
                MERGE (m)-[:PROCESSED_IN]->(p)
            """, {"mat_id": material_id, "proc_id": process_id})

    def delete_document_material_process_links(self, document_id: str) -> None:
        with self.driver.session() as session:
            session.run("""
                MATCH (d:Document {id: $doc_id})-[:DESCRIBES_PROCESS]->(p:Process)
                MATCH (m:Material)-[r:PROCESSED_IN]->(p)
                DELETE r
            """, {"doc_id": document_id})
    
    def save_document(self, document: DocumentDTO, *, content_language: str | None = None):
        """Сохраняет документ как узел в графе."""
        lang = (content_language or self._default_display_lang()).strip().lower()
        if lang not in ("ru", "en"):
            lang = self._default_display_lang()
        with self.driver.session() as session:
            session.run("""
                MERGE (d:Document {id: $id})
                SET d.title = $title,
                    d.document_type = $document_type,
                    d.authors = $authors,
                    d.organizations = $organizations,
                    d.year = $year,
                    d.file_path = $file_path,
                    d.content_hash = $content_hash,
                    d.canonical_source = $canonical_source,
                    d.file_hash = $file_hash,
                    d.chunks_count = $chunks_count,
                    d.images_count = $images_count,
                    d.content_language = $content_language,
                    d.created_at = $created_at
            """, {
                "id": str(document.id),
                "title": document.title,
                "document_type": document.document_type.value,
                "authors": document.authors,
                "organizations": document.organizations,
                "year": document.year,
                "file_path": document.file_path,
                "content_hash": document.content_hash,
                "canonical_source": document.canonical_source,
                "file_hash": document.file_hash,
                "chunks_count": len(document.chunks),
                "images_count": len(document.images),
                "content_language": lang,
                "created_at": document.created_at.isoformat()
            })

            for chunk in document.chunks:
                if not chunk.text or not chunk.text.strip():
                    continue
                session.run("""
                    MERGE (c:DocumentChunk {id: $id})
                    SET c.text = $text,
                        c.page_number = $page_number,
                        c.chunk_index = $chunk_index
                    WITH c
                    MATCH (d:Document {id: $doc_id})
                    MERGE (d)-[:HAS_CHUNK]->(c)
                """, {
                    "id": str(chunk.id),
                    "text": chunk.text,
                    "page_number": chunk.page_number,
                    "chunk_index": chunk.chunk_index,
                    "doc_id": str(document.id),
                })

    def save_figure_gallery(self, document_id: str, images: list) -> None:
        """One Figures blob per document + individual Image nodes (not shown on graph)."""
        seen_keys: set[str] = set()
        unique_images: list = []
        for image in images:
            dedupe_key = (image.file_path or "").strip() or str(image.id)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            unique_images.append(image)
        images = unique_images

        if not images:
            with self.driver.session() as session:
                session.run("""
                    MATCH (d:Document {id: $doc_id})-[:HAS_FIGURES]->(g:FigureGallery)
                    OPTIONAL MATCH (g)-[:CONTAINS_IMAGE]->(i:Image)
                    DETACH DELETE i, g
                """, {"doc_id": document_id})
            return

        gallery_id = f"{document_id}:figures"
        items = []
        for image in images:
            items.append({
                "id": str(image.id),
                "caption": image.caption or "",
                "page_number": image.page_number,
                "image_type": image.image_type.value,
                "storage_key": image.file_path,
            })
        items_json = json.dumps(items, ensure_ascii=False)

        type_counts: dict[str, int] = {}
        for image in images:
            key = image.image_type.value
            type_counts[key] = type_counts.get(key, 0) + 1
        summary = ", ".join(f"{v} {k}" for k, v in sorted(type_counts.items()))

        with self.driver.session() as session:
            session.run("""
                MATCH (d:Document {id: $doc_id})
                OPTIONAL MATCH (d)-[:HAS_FIGURES]->(old:FigureGallery)
                OPTIONAL MATCH (old)-[:CONTAINS_IMAGE]->(oi:Image)
                DETACH DELETE oi, old
            """, {"doc_id": document_id})

            session.run("""
                MATCH (d:Document {id: $doc_id})
                MERGE (g:FigureGallery {id: $gallery_id})
                SET g.name = $name,
                    g.document_id = $doc_id,
                    g.image_count = $count,
                    g.type_summary = $summary,
                    g.items_json = $items_json
                MERGE (d)-[:HAS_FIGURES]->(g)
            """, {
                "doc_id": document_id,
                "gallery_id": gallery_id,
                "name": f"Figures ({len(images)})",
                "count": len(images),
                "summary": summary,
                "items_json": items_json,
            })

            for image in images:
                session.run("""
                    MATCH (g:FigureGallery {id: $gallery_id})
                    MERGE (i:Image {id: $img_id})
                    SET i.image_type = $image_type,
                        i.file_path = $file_path,
                        i.caption = $caption,
                        i.ai_description = $ai_description,
                        i.page_number = $page_number,
                        i.document_id = $doc_id
                    MERGE (g)-[:CONTAINS_IMAGE]->(i)
                """, {
                    "gallery_id": gallery_id,
                    "img_id": str(image.id),
                    "image_type": image.image_type.value,
                    "file_path": image.file_path,
                    "caption": image.caption,
                    "ai_description": image.ai_description or "",
                    "page_number": image.page_number,
                    "doc_id": document_id,
                })

    def get_image_storage_key(self, document_id: str, image_id: str) -> str | None:
        with self.driver.session() as session:
            record = session.run("""
                MATCH (d:Document {id: $doc_id})-[:HAS_FIGURES]->(:FigureGallery)
                      -[:CONTAINS_IMAGE]->(i:Image {id: $img_id})
                RETURN i.file_path AS path
                LIMIT 1
            """, {"doc_id": document_id, "img_id": image_id}).single()
            if record and record.get("path"):
                return str(record["path"])
            legacy = session.run("""
                MATCH (d:Document {id: $doc_id})-[:CONTAINS_IMAGE]->(i:Image {id: $img_id})
                RETURN i.file_path AS path
                LIMIT 1
            """, {"doc_id": document_id, "img_id": image_id}).single()
            if legacy and legacy.get("path"):
                return str(legacy["path"])
        return None

    def list_document_figures(self, document_id: str) -> list[dict]:
        with self.driver.session() as session:
            record = session.run("""
                MATCH (d:Document {id: $doc_id})-[:HAS_FIGURES]->(g:FigureGallery)
                RETURN g.items_json AS items_json, g.items AS items_legacy
            """, {"doc_id": document_id}).single()
            if record and record.get("items_json"):
                try:
                    parsed = json.loads(str(record["items_json"]))
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    pass
            if record and record.get("items_legacy"):
                legacy = record["items_legacy"]
                if isinstance(legacy, list):
                    return list(legacy)

            rows = session.run("""
                MATCH (d:Document {id: $doc_id})-[:HAS_FIGURES]->(:FigureGallery)
                      -[:CONTAINS_IMAGE]->(i:Image)
                RETURN i.id AS id,
                       i.caption AS caption,
                       i.page_number AS page_number,
                       i.image_type AS image_type,
                       i.file_path AS storage_key
                ORDER BY i.page_number, i.id
            """, {"doc_id": document_id})
            return [
                {
                    "id": str(r["id"]),
                    "caption": r.get("caption") or "",
                    "page_number": r.get("page_number"),
                    "image_type": r.get("image_type") or "other",
                    "storage_key": r.get("storage_key") or "",
                }
                for r in rows
            ]
    
    def find_document_by_file_path(self, file_path: str) -> dict | None:
        """Find an ingested document by source path or URL."""
        matches = self.find_all_documents_by_source(file_path)
        return matches[0] if matches else None

    def find_all_documents_by_source(self, source: str) -> list[dict]:
        """Find all documents matching a URL or canonical source (including legacy rows)."""
        from ingestion.dedup import canonicalize_url

        canonical = canonicalize_url(source)
        with self.driver.session() as session:
            result = session.run("""
                MATCH (d:Document)
                RETURN d.id as id, d.title as title, d.file_path as file_path,
                       d.content_hash as content_hash, d.canonical_source as canonical_source,
                       d.file_hash as file_hash, d.created_at as created_at
            """)
            rows = [dict(record) for record in result]

        matches: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            doc_id = row["id"]
            if doc_id in seen:
                continue
            row_path = row.get("file_path") or ""
            row_canonical = row.get("canonical_source") or ""
            if (
                row_canonical == canonical
                or row_path == source
                or row_path == canonical
                or (row_path and canonicalize_url(row_path) == canonical)
            ):
                seen.add(doc_id)
                matches.append(row)

        matches.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return matches

    def find_all_documents_by_file_hash(self, file_hash: str) -> list[dict]:
        with self.driver.session() as session:
            result = session.run("""
                MATCH (d:Document)
                WHERE d.file_hash = $hash
                RETURN d.id as id, d.title as title, d.file_path as file_path,
                       d.content_hash as content_hash, d.file_hash as file_hash,
                       d.created_at as created_at
                ORDER BY d.created_at DESC
            """, {"hash": file_hash})
            return [dict(record) for record in result]

    def find_all_documents_by_filename(self, filename: str) -> list[dict]:
        """Match documents uploaded under the same original filename."""
        basename = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        with self.driver.session() as session:
            result = session.run("""
                MATCH (d:Document)
                RETURN d.id as id, d.title as title, d.file_path as file_path,
                       d.content_hash as content_hash, d.file_hash as file_hash,
                       d.created_at as created_at
            """)
            rows = [dict(record) for record in result]

        matches = []
        for row in rows:
            path = (row.get("file_path") or "").lower()
            if path == filename.lower() or path.endswith(f"/{basename}") or path == basename:
                matches.append(row)
        matches.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return matches

    def find_all_documents_by_content_hash(self, content_hash: str) -> list[dict]:
        with self.driver.session() as session:
            result = session.run("""
                MATCH (d:Document {content_hash: $hash})
                RETURN d.id as id, d.title as title, d.file_path as file_path,
                       d.content_hash as content_hash, d.created_at as created_at
                ORDER BY d.created_at DESC
            """, {"hash": content_hash})
            return [dict(record) for record in result]

    def find_document_by_canonical_source(self, canonical_source: str) -> dict | None:
        matches = self.find_all_documents_by_source(canonical_source)
        return matches[0] if matches else None

    def find_document_by_content_hash(self, content_hash: str) -> dict | None:
        with self.driver.session() as session:
            result = session.run("""
                MATCH (d:Document {content_hash: $hash})
                RETURN d.id as id, d.title as title, d.file_path as file_path,
                       d.content_hash as content_hash, d.canonical_source as canonical_source
                LIMIT 1
            """, {"hash": content_hash})
            record = result.single()
            return dict(record) if record else None

    def find_document_by_file_hash(self, file_hash: str) -> dict | None:
        matches = self.find_all_documents_by_file_hash(file_hash)
        return matches[0] if matches else None

    def list_document_fingerprints(self) -> list[dict]:
        with self.driver.session() as session:
            result = session.run("""
                MATCH (d:Document)
                RETURN d.id as id, d.title as title, d.file_path as file_path,
                       d.content_hash as content_hash, d.canonical_source as canonical_source,
                       d.file_hash as file_hash, d.created_at as created_at
                ORDER BY d.created_at DESC
            """)
            return [dict(record) for record in result]

    def get_document_title(self, document_id: str) -> str | None:
        with self.driver.session() as session:
            record = session.run(
                "MATCH (d:Document {id: $id}) RETURN d.title AS title",
                {"id": document_id},
            ).single()
            return record["title"] if record else None

    def delete_document(self, document_id: str) -> bool:
        """Remove a document and all ingestion entities owned exclusively by it."""
        with self.driver.session() as session:
            exists = session.run(
                "MATCH (d:Document {id: $id}) RETURN d.id AS id",
                {"id": document_id},
            ).single()
            if not exists:
                return False

            session.run(
                """
                MATCH (d:Document {id: $id})<-[:DESCRIBED_IN]-(e:Experiment)
                DETACH DELETE e
                """,
                {"id": document_id},
            )
            session.run(
                """
                MATCH (d:Document {id: $id})-[:MENTIONS_MATERIAL]->(m:Material)
                WHERE NOT EXISTS {
                    MATCH (other:Document)-[:MENTIONS_MATERIAL]->(m)
                    WHERE other.id <> $id
                }
                DETACH DELETE m
                """,
                {"id": document_id},
            )
            session.run(
                """
                MATCH (m:Material)
                WHERE m.source_document_id = $id
                  AND NOT EXISTS {
                    MATCH (:Document)-[:MENTIONS_MATERIAL]->(m)
                  }
                DETACH DELETE m
                """,
                {"id": document_id},
            )
            session.run(
                """
                MATCH (d:Document {id: $id})-[:DESCRIBES_PROCESS]->(p:Process)
                WHERE NOT EXISTS {
                    MATCH (other:Document)-[:DESCRIBES_PROCESS]->(p)
                    WHERE other.id <> $id
                }
                DETACH DELETE p
                """,
                {"id": document_id},
            )
            session.run(
                """
                MATCH (d:Document {id: $id})-[:MENTIONS_EQUIPMENT]->(eq:Equipment)
                WHERE NOT EXISTS {
                    MATCH (:Document)-[:MENTIONS_EQUIPMENT]->(eq)
                }
                DETACH DELETE eq
                """,
                {"id": document_id},
            )
            session.run(
                """
                MATCH (d:Document {id: $id})-[:FROM_FACILITY]->(f:Facility)
                WHERE NOT EXISTS {
                    MATCH (:Document)-[:FROM_FACILITY]->(f)
                }
                DETACH DELETE f
                """,
                {"id": document_id},
            )
            session.run(
                """
                MATCH (t:Team)-[:AUTHORED]->(d:Document {id: $id})
                WHERE NOT EXISTS {
                    MATCH (t)-[:AUTHORED]->(other:Document)
                    WHERE other.id <> $id
                }
                DETACH DELETE t
                """,
                {"id": document_id},
            )
            session.run(
                """
                MATCH (d:Document {id: $id})-[:AUTHORED_BY]->(x:Expert)
                WHERE NOT EXISTS {
                    MATCH (other:Document)-[:AUTHORED_BY]->(x)
                    WHERE other.id <> $id
                }
                DETACH DELETE x
                """,
                {"id": document_id},
            )

        self.delete_document_topics(document_id)
        self.delete_document_material_process_links(document_id)

        with self.driver.session() as session:
            session.run(
                """
                MATCH (d:Document {id: $id})
                OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:DocumentChunk)
                OPTIONAL MATCH (d)-[:HAS_FIGURES]->(g:FigureGallery)
                OPTIONAL MATCH (g)-[:CONTAINS_IMAGE]->(i:Image)
                OPTIONAL MATCH (d)-[:CONTAINS_IMAGE]->(i2:Image)
                DETACH DELETE c, i, i2, g, d
                """,
                {"id": document_id},
            )

        self.purge_orphan_entities()
        return True

    def purge_all_ingested_data(self) -> dict:
        """
        Remove all documents and ingestion-derived knowledge graph entities.
        Keeps Neo4j schema; wipes documents, chunks, experiments, materials, etc.
        """
        label_keys = {
            "Document": "documents",
            "DocumentChunk": "document_chunks",
            "Image": "images",
            "Experiment": "experiments",
            "Material": "materials",
            "Team": "teams",
            "Process": "processes",
            "Equipment": "equipment",
            "Facility": "facilities",
            "Expert": "experts",
            "FigureGallery": "figure_galleries",
            "RegimeParameter": "regime_parameters",
            "Property": "properties",
            "PropertyValue": "property_values",
        }
        deleted: dict[str, int] = {}
        with self.driver.session() as session:
            for label, key in label_keys.items():
                count_result = session.run(
                    f"MATCH (n:{label}) RETURN count(n) AS c"
                ).single()
                count = int(count_result["c"]) if count_result else 0
                if count:
                    session.run(f"MATCH (n:{label}) DETACH DELETE n")
                deleted[key] = count

            edges = session.run(
                "MATCH ()-[r]->() DELETE r RETURN count(r) AS c"
            ).single()
            deleted["remaining_edges"] = 0

        total_nodes = sum(v for k, v in deleted.items() if k != "remaining_edges")
        orphans = self.purge_orphan_entities()
        deleted["orphans_removed"] = orphans.get("total", 0)

        remaining = self._count_ingestion_nodes()
        if any(remaining.values()):
            logger.warning("Residual ingestion nodes after purge: %s", remaining)
            with self.driver.session() as session:
                session.run(
                    """
                    MATCH (n)
                    WHERE any(l IN labels(n) WHERE l IN $labels)
                    DETACH DELETE n
                    """,
                    {"labels": list(label_keys.keys())},
                )
            orphans = self.purge_orphan_entities()
            remaining = self._count_ingestion_nodes()
        deleted["remaining"] = remaining

        logger.info("Purged knowledge graph: %s", deleted)
        return {
            "deleted": deleted,
            "total_nodes_removed": total_nodes + orphans.get("total", 0),
            "remaining": remaining,
        }

    def _count_ingestion_nodes(self) -> dict[str, int]:
        labels = [
            "Document", "DocumentChunk", "Image", "Experiment", "Material",
            "Team", "Process", "Equipment", "Facility", "Expert",
            "FigureGallery", "RegimeParameter", "Property", "PropertyValue",
        ]
        counts: dict[str, int] = {}
        with self.driver.session() as session:
            for label in labels:
                record = session.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()
                counts[label.lower()] = int(record["c"]) if record else 0
        return counts

    def purge_orphan_entities(self) -> dict:
        """Remove ingestion entities not connected to any Document."""
        removed: dict[str, int] = {}
        with self.driver.session() as session:
            queries = {
                "materials": """
                    MATCH (m:Material)
                    WHERE NOT (m)<-[:MENTIONS_MATERIAL]-(:Document)
                      AND NOT EXISTS {
                        MATCH (e:Experiment)-[:USES_MATERIAL]->(m)
                        MATCH (e)-[:DESCRIBED_IN]->(:Document)
                      }
                      AND NOT EXISTS {
                        MATCH (:Document {id: m.source_document_id})
                      }
                    DETACH DELETE m
                    RETURN count(m) AS c
                """,
                "experiments": """
                    MATCH (e:Experiment)
                    WHERE NOT (e)-[:DESCRIBED_IN]->(:Document)
                    DETACH DELETE e
                    RETURN count(e) AS c
                """,
                "processes": """
                    MATCH (p:Process)
                    WHERE NOT ()-[:DESCRIBES_PROCESS|USES_PROCESS|PROCESSED_IN]->(p)
                    DETACH DELETE p
                    RETURN count(p) AS c
                """,
                "teams": """
                    MATCH (t:Team)
                    WHERE NOT (t)-[:AUTHORED]->(:Document)
                    DETACH DELETE t
                    RETURN count(t) AS c
                """,
                "experts": """
                    MATCH (x:Expert)
                    WHERE NOT (x)-[:AUTHORED_BY]->(:Document)
                      AND NOT (x)<-[:MEMBER_OF]-(:Team)-[:AUTHORED]->(:Document)
                    DETACH DELETE x
                    RETURN count(x) AS c
                """,
                "equipment": """
                    MATCH (e:Equipment)
                    WHERE NOT ()-[:MENTIONS_EQUIPMENT|USES_EQUIPMENT]->(e)
                    DETACH DELETE e
                    RETURN count(e) AS c
                """,
                "facilities": """
                    MATCH (f:Facility)
                    WHERE NOT ()-[:FROM_FACILITY|REFERENCES]->(f)
                    DETACH DELETE f
                    RETURN count(f) AS c
                """,
                "properties": """
                    MATCH (p:Property)
                    WHERE NOT ()-[:HAS_PROPERTY|MEASURED|HAS_VALUE]->(p)
                    OPTIONAL MATCH (p)-[:HAS_VALUE]->(v:PropertyValue)
                    DETACH DELETE p, v
                    RETURN count(p) AS c
                """,
                "property_values": """
                    MATCH (v:PropertyValue)
                    WHERE NOT ()-[:HAS_VALUE]->(v)
                    DETACH DELETE v
                    RETURN count(v) AS c
                """,
                "regime_parameters": """
                    MATCH (rp:RegimeParameter)
                    WHERE NOT ()-[:HAS_REGIME_PARAM|HAS_TOPIC]->(rp)
                    DETACH DELETE rp
                    RETURN count(rp) AS c
                """,
                "figure_galleries": """
                    MATCH (g:FigureGallery)
                    WHERE NOT ()-[:HAS_FIGURES]->(g)
                    OPTIONAL MATCH (g)-[:CONTAINS_IMAGE]->(i:Image)
                    DETACH DELETE g, i
                    RETURN count(g) AS c
                """,
                "images": """
                    MATCH (i:Image)
                    WHERE NOT ()-[:CONTAINS_IMAGE]->(i)
                    DETACH DELETE i
                    RETURN count(i) AS c
                """,
                "chunks": """
                    MATCH (c:DocumentChunk)
                    WHERE NOT ()-[:HAS_CHUNK]->(c)
                    DETACH DELETE c
                    RETURN count(c) AS c
                """,
            }
            for key, query in queries.items():
                record = session.run(query).single()
                count = int(record["c"]) if record and record.get("c") is not None else 0
                if count:
                    removed[key] = count

            stray = session.run("""
                MATCH (n)
                WHERE any(l IN labels(n) WHERE l IN [
                  'Document','DocumentChunk','Image','Experiment','Material','Team',
                  'Process','Equipment','Facility','Expert','FigureGallery',
                  'RegimeParameter','Property','PropertyValue'
                ])
                RETURN labels(n)[0] AS label, count(n) AS c
            """)
            removed["remaining_by_label"] = {
                str(r["label"]): int(r["c"]) for r in stray if r["c"]
            }

        total = sum(v for k, v in removed.items() if k != "remaining_by_label")
        if total:
            logger.info("Purged orphan entities: %s", removed)
        return {"removed": removed, "total": total}

    def list_documents(self, limit: int = 100) -> list[dict]:
        """List ingested documents."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (d:Document)
                OPTIONAL MATCH (d)-[:HAS_FIGURES]->(g:FigureGallery)
                RETURN d.id as id, d.title as title,
                       d.document_type as document_type,
                       d.authors as authors,
                       d.year as year,
                       d.file_path as file_path,
                       d.chunks_count as chunks_count,
                       coalesce(g.image_count, d.images_count, 0) as images_count,
                       d.created_at as created_at
                ORDER BY d.created_at DESC
                LIMIT $limit
            """, {"limit": limit})
            return [dict(record) for record in result]

    def delete_document_enrichment_people(self, document_id: str) -> None:
        """Remove Team and Expert nodes linked to a document before re-enrichment."""
        with self.driver.session() as session:
            session.run("""
                MATCH (d:Document {id: $doc_id})
                OPTIONAL MATCH (d)-[:AUTHORED_BY]->(x:Expert)
                OPTIONAL MATCH (t:Team)-[:AUTHORED]->(d)
                DETACH DELETE x, t
            """, {"doc_id": document_id})

    def delete_document_topics(self, document_id: str) -> None:
        """Remove legacy topic tags (stored as RegimeParameter) for a document."""
        with self.driver.session() as session:
            session.run("""
                MATCH (d:Document {id: $doc_id})-[r:HAS_TOPIC]->(rp:RegimeParameter)
                DELETE r
                WITH DISTINCT rp
                WHERE NOT (rp)--()
                DETACH DELETE rp
            """, {"doc_id": document_id})

    def document_has_entities(self, document_id: str) -> bool:
        """True when document has enrichment links (process, expert, team, experiment)."""
        with self.driver.session() as session:
            record = session.run("""
                MATCH (d:Document {id: $id})
                OPTIONAL MATCH (d)-[:DESCRIBES_PROCESS]->(p)
                OPTIONAL MATCH (d)-[:AUTHORED_BY]->(ex)
                OPTIONAL MATCH (t:Team)-[:AUTHORED]->(d)
                OPTIONAL MATCH (exp:Experiment)-[:DESCRIBED_IN]->(d)
                RETURN (p IS NOT NULL OR ex IS NOT NULL OR t IS NOT NULL OR exp IS NOT NULL) AS enriched
            """, {"id": document_id}).single()
            return bool(record and record["enriched"])

    def backfill_material_document_links(self) -> int:
        """Link existing materials to documents via source_document_id."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (m:Material)
                WHERE m.source_document_id IS NOT NULL
                MATCH (d:Document {id: m.source_document_id})
                MERGE (d)-[:MENTIONS_MATERIAL]->(m)
                RETURN count(m) as linked
            """)
            record = result.single()
            return int(record["linked"] or 0) if record else 0

    def load_document_dto(self, document_id: str) -> DocumentDTO | None:
        """Rebuild DocumentDTO from Neo4j for re-enrichment."""
        with self.driver.session() as session:
            record = session.run("""
                MATCH (d:Document {id: $id})
                OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:DocumentChunk)
                WITH d, c ORDER BY c.chunk_index
                RETURN d,
                       collect({
                           id: c.id,
                           text: c.text,
                           page_number: c.page_number,
                           chunk_index: c.chunk_index
                       }) as chunks
            """, {"id": document_id}).single()
            if not record:
                return None

            node = dict(record["d"])
            raw_chunks = [
                c for c in record["chunks"]
                if c.get("id") and c.get("text")
            ]
            chunks = [
                DocumentChunkDTO(
                    id=UUID(str(c["id"])),
                    document_id=UUID(document_id),
                    text=c["text"],
                    chunk_index=int(c.get("chunk_index") or i),
                    page_number=c.get("page_number"),
                )
                for i, c in enumerate(raw_chunks)
            ]
            doc_type = node.get("document_type") or "article"
            try:
                dtype = DocumentType(doc_type)
            except ValueError:
                dtype = DocumentType.OTHER

            return DocumentDTO(
                id=UUID(document_id),
                title=node.get("title") or "Untitled",
                document_type=dtype,
                authors=node.get("authors") or [],
                organizations=node.get("organizations") or [],
                year=node.get("year"),
                file_path=node.get("file_path") or "",
                content_hash=node.get("content_hash"),
                canonical_source=node.get("canonical_source"),
                file_hash=node.get("file_hash"),
                chunks=chunks,
            )

    # ================== READ (для API) ==================
    
    def get_stats(self) -> dict:
        """Общая статистика графа."""
        with self.driver.session() as session:
            counts = {}
            for label in [
                "Material", "Experiment", "Document", "Property",
                "Image", "RegimeParameter", "Team", "Process",
                "Equipment", "Facility", "Expert",
            ]:
                result = session.run(f"MATCH (n:{label}) RETURN count(n) as c").single()
                counts[label.lower() + "s"] = result["c"]

            result = session.run("MATCH ()-[r]->() RETURN count(r) as c").single()
            counts["edges"] = result["c"]

            class_dist = {}
            result = session.run("""
                MATCH (m:Material)
                RETURN m.material_class as cls, count(m) as c
            """)
            for record in result:
                class_dist[record["cls"]] = record["c"]
            counts["material_classes"] = class_dist

            regime_dist = {}
            result = session.run("""
                MATCH (e:Experiment)
                RETURN e.regime_type as rt, count(e) as c
            """)
            for record in result:
                regime_dist[record["rt"]] = record["c"]
            counts["regime_types"] = regime_dist

            status_dist = {"completed": 0, "ongoing": 0, "planned": 0}
            result = session.run("""
                MATCH (e:Experiment)
                RETURN coalesce(e.status, 'completed') as st, count(e) as c
            """)
            for record in result:
                key = record["st"] or "completed"
                if key in status_dist:
                    status_dist[key] = record["c"]
                else:
                    status_dist["completed"] += record["c"]
            counts["experiment_status"] = status_dist

            return counts
    
    def list_materials(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Список материалов."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (m:Material)
                OPTIONAL MATCH (m)-[:HAS_PROPERTY]->(p)
                WITH m, count(p) as properties_count
                OPTIONAL MATCH (e:Experiment)-[:USES_MATERIAL]->(m)
                WITH m, properties_count, count(e) as experiments_count
                RETURN m.id as id, m.name as name, 
                       m.material_class as material_class,
                       m.aliases as aliases,
                       properties_count,
                       experiments_count
                ORDER BY m.name
                SKIP $offset LIMIT $limit
            """, {"offset": offset, "limit": limit})
            
            return [dict(record) for record in result]
    
    def get_material_details(self, material_id: str) -> dict | None:
        """Детальная информация о материале со связями."""
        with self.driver.session() as session:
            # Основная информация
            result = session.run("""
                MATCH (m:Material {id: $id})
                RETURN m
            """, {"id": material_id})
            record = result.single()
            if not record:
                return None
            
            material = dict(record["m"])
            
            # Свойства
            props_result = session.run("""
                MATCH (m:Material {id: $id})-[:HAS_PROPERTY]->(p)-[:HAS_VALUE]->(v)
                RETURN p.canonical_name as name, p.category as category,
                       p.unit as unit, v.value as value,
                       v.value_min as value_min, v.value_max as value_max,
                       v.source_text as source_text
            """, {"id": material_id})
            material["properties"] = [dict(r) for r in props_result]
            
            # Эксперименты
            exp_result = session.run("""
                MATCH (e:Experiment)-[:USES_MATERIAL]->(m:Material {id: $id})
                OPTIONAL MATCH (e)-[:DESCRIBED_IN]->(d:Document)
                RETURN e.id as id, e.regime_name as regime,
                       e.regime_type as regime_type,
                       e.conclusions as conclusions,
                       d.title as document_title
                ORDER BY e.created_at DESC
                LIMIT 50
            """, {"id": material_id})
            material["experiments"] = [dict(r) for r in exp_result]
            
            return material
    
    def list_experiments(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Список экспериментов."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (e:Experiment)
                OPTIONAL MATCH (e)-[:USES_MATERIAL]->(m:Material)
                OPTIONAL MATCH (e)-[:DESCRIBED_IN]->(d:Document)
                RETURN e.id as id, e.regime_name as regime,
                       e.regime_type as regime_type,
                       m.name as material_name,
                       d.title as document_title
                ORDER BY e.created_at DESC
                SKIP $offset LIMIT $limit
            """, {"offset": offset, "limit": limit})
            
            return [dict(record) for record in result]
    
    def get_experiment_details(self, experiment_id: str) -> dict | None:
        """Детали эксперимента."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (e:Experiment {id: $id})
                OPTIONAL MATCH (e)-[:USES_MATERIAL]->(m:Material)
                OPTIONAL MATCH (e)-[:DESCRIBED_IN]->(d:Document)
                RETURN e, m.name as material_name, d.title as document_title
            """, {"id": experiment_id})
            record = result.single()
            if not record:
                return None
            
            exp = dict(record["e"])
            exp["material_name"] = record["material_name"]
            exp["document_title"] = record["document_title"]
            
            # Параметры режима
            params_result = session.run("""
                MATCH (e:Experiment {id: $id})-[r:HAS_REGIME_PARAM]->(rp:RegimeParameter)
                RETURN rp.name as name, r.value as value, r.unit as unit
            """, {"id": experiment_id})
            exp["regime_parameters"] = [dict(r) for r in params_result]
            
            # Измеренные свойства
            props_result = session.run("""
                MATCH (e:Experiment {id: $id})-[r:MEASURED]->(p:Property)
                RETURN p.canonical_name as name, p.category as category,
                       r.value as value, r.unit as unit
            """, {"id": experiment_id})
            exp["measured_properties"] = [dict(r) for r in props_result]
            
            return exp

    def get_property_details(self, canonical_name: str) -> dict | None:
        """Measured values for a property (from experiments and materials)."""
        name = (canonical_name or "").strip()
        if name.startswith("prop:"):
            name = name[5:]
        if not name:
            return None

        with self.driver.session() as session:
            record = session.run(
                """
                MATCH (p:Property {canonical_name: $name})
                OPTIONAL MATCH (e:Experiment)-[mr:MEASURED]->(p)
                OPTIONAL MATCH (e)-[:DESCRIBED_IN]->(d:Document)
                WITH p,
                     collect(DISTINCT {
                         source: 'experiment',
                         experiment_id: e.id,
                         experiment_name: coalesce(e.regime_name, e.regime_type, e.id),
                         document_title: d.title,
                         value: mr.value,
                         unit: mr.unit,
                         source_text: mr.source_text
                     }) AS experiment_values
                OPTIONAL MATCH (m:Material)-[:HAS_PROPERTY]->(p)
                OPTIONAL MATCH (p)-[:HAS_VALUE]->(v:PropertyValue)
                WHERE v.id = m.id + '_' + p.canonical_name
                WITH p, experiment_values,
                     collect(DISTINCT {
                         source: 'material',
                         material_id: m.id,
                         material_name: m.name,
                         value: v.value,
                         unit: coalesce(v.unit, p.unit),
                         source_text: v.source_text
                     }) AS material_values
                OPTIONAL MATCH (p)<-[:MEASURED]-(:Experiment)-[:DESCRIBED_IN]->(doc:Document)
                RETURN p,
                       collect(DISTINCT doc.content_language) AS doc_langs,
                       experiment_values,
                       material_values
                """,
                {"name": name},
            ).single()
            if not record:
                return None

            prop = dict(record["p"])
            lang = self._lang_from_doc_langs(record.get("doc_langs"))
            measurements: list[dict] = []
            seen: set[tuple] = set()

            def _append(row: dict | None) -> None:
                if not row or not row.get("value"):
                    return
                if row.get("source") == "experiment" and not row.get("experiment_id"):
                    return
                if row.get("source") == "material" and not row.get("material_id"):
                    return
                key = (
                    row.get("source"),
                    row.get("experiment_id"),
                    row.get("material_id"),
                    str(row.get("value")),
                )
                if key in seen:
                    return
                seen.add(key)
                measurements.append(dict(row))

            for row in record["experiment_values"] or []:
                _append(row)
            for row in record["material_values"] or []:
                _append(row)

            return {
                "canonical_name": name,
                "display_label": property_display_label(name, lang=lang),
                "category": prop.get("category"),
                "unit": prop.get("unit"),
                "measurements": measurements,
            }
    
    def get_subgraph(self, center_node_id: str, depth: int = 2, max_nodes: int = 100) -> dict:
        """
        Получает подграф для визуализации.
        
        Args:
            center_node_id: ID центрального узла
            depth: Глубина обхода
            max_nodes: Максимальное количество узлов
        
        Returns:
            {nodes: [...], edges: [...]}
        """
        with self.driver.session() as session:
            result = session.run(f"""
                MATCH path = (center {{id: $id}})-[*1..{depth}]-(n)
                WITH nodes(path) as nodes, relationships(path) as rels
                UNWIND nodes as node
                WITH DISTINCT node, collect(DISTINCT rels) as all_rels
                LIMIT $max_nodes
                RETURN node
            """, {"id": center_node_id, "max_nodes": max_nodes})
            
            nodes = []
            node_ids = set()
            for record in result:
                node = record["node"]
                node_id = node.get("id")
                if node_id and node_id not in node_ids:
                    nodes.append({
                        "id": node_id,
                        "label": node.get("name") or node.get("canonical_name") or node.get("regime_name") or node_id[:8],
                        "type": list(node.labels)[0] if node.labels else "Unknown",
                        "properties": {k: v for k, v in dict(node).items() if k != "id"}
                    })
                    node_ids.add(node_id)
            
            # Получаем связи между найденными узлами
            edges = []
            if node_ids:
                edges_result = session.run("""
                    MATCH (a)-[r]->(b)
                    WHERE a.id IN $ids AND b.id IN $ids
                    RETURN a.id as source, b.id as target, type(r) as type
                """, {"ids": list(node_ids)})
                
                for record in edges_result:
                    edges.append({
                        "source": record["source"],
                        "target": record["target"],
                        "type": record["type"]
                    })
            
            return {"nodes": nodes, "edges": edges}
    
    def get_node_neighbors(self, node_id: str, limit: int = 40) -> dict:
        """1-hop neighbors for the entity panel (canvas stays link-free)."""
        skip = list(SKIP_VISUAL_REL_TYPES)
        edge_labels = list(VISUAL_NODE_LABELS) + ["Property", "RegimeParameter"]
        with self.driver.session() as session:
            center = session.run(
                """
                MATCH (n {id: $id})
                RETURN n AS node, labels(n)[0] AS label
                LIMIT 1
                """,
                {"id": node_id},
            ).single()
            if not center:
                return {"nodes": [], "edges": []}

            neighbors = list(
                session.run(
                    """
                    MATCH (n {id: $id})-[r]-(m)
                    WHERE NOT type(r) IN $skip
                    WITH DISTINCT m AS node, labels(m)[0] AS label
                    ORDER BY toLower(
                        coalesce(node.name, node.title, node.regime_name, node.canonical_name, node.id)
                    )
                    LIMIT $limit
                    RETURN node, label
                    """,
                    {"id": node_id, "skip": skip, "limit": limit},
                )
            )
            rows = [center, *neighbors]
            return self._build_visual_graph(session, rows, edge_labels)

    def get_full_graph(
        self,
        limit: int = 3_000,
        document_id: str | None = None,
        doc_limit: int = 25,
        hub_only: bool = False,
    ) -> dict:
        """Knowledge graph for visualization. Pass document_id for the full document subgraph."""
        if document_id:
            return self._get_document_graph(document_id, node_limit=max(limit, 10_000))
        if hub_only:
            return self._get_document_hubs(doc_limit)
        labels = list(VISUAL_NODE_LABELS)
        edge_labels = labels + ["Property", "RegimeParameter"]
        skip = list(SKIP_VISUAL_REL_TYPES)

        with self.driver.session() as session:
            nodes_result = session.run(
                """
                MATCH (d:Document)
                WITH d ORDER BY coalesce(d.created_at, '') DESC, d.title
                LIMIT $doc_limit

                OPTIONAL MATCH (d)-[r1]-(n1)
                WHERE NOT type(r1) IN $skip
                  AND any(l IN labels(n1) WHERE l IN $labels)

                OPTIONAL MATCH (e:Experiment)-[:DESCRIBED_IN]->(d)
                OPTIONAL MATCH (e)-[:USES_MATERIAL]->(m:Material)
                OPTIONAL MATCH (e)-[:MEASURED]->(p:Property)
                OPTIONAL MATCH (e)-[:HAS_REGIME_PARAM]->(rp:RegimeParameter)
                OPTIONAL MATCH (e)-[:USES_PROCESS]->(pr:Process)

                WITH [x IN collect(DISTINCT d) + collect(DISTINCT n1)
                     + collect(DISTINCT e) + collect(DISTINCT m) + collect(DISTINCT p)
                     + collect(DISTINCT rp) + collect(DISTINCT pr) WHERE x IS NOT NULL] AS raw_nodes
                UNWIND raw_nodes AS node
                WITH DISTINCT node
                WHERE node IS NOT NULL
                RETURN node, labels(node)[0] AS label
                LIMIT $node_limit
                """,
                {
                    "labels": labels,
                    "skip": skip,
                    "doc_limit": doc_limit,
                    "node_limit": limit,
                },
            )
            return self._build_visual_graph(session, nodes_result, edge_labels)

    def _get_document_hubs(self, doc_limit: int = 25) -> dict:
        """Recent document nodes only — fast first paint for collapsed hub view."""
        with self.driver.session() as session:
            nodes_result = session.run(
                """
                MATCH (d:Document)
                WITH d ORDER BY coalesce(d.created_at, '') DESC, d.title
                LIMIT $doc_limit
                RETURN d AS node, labels(d)[0] AS label
                """,
                {"doc_limit": doc_limit},
            )
            return self._build_visual_graph(session, nodes_result, ["Document"])

    def _get_document_graph(self, document_id: str, node_limit: int = 10_000) -> dict:
        """Entities linked to one document (direct links + experiment chains)."""
        edge_labels = list(VISUAL_NODE_LABELS) + ["Property", "RegimeParameter"]
        skip = list(SKIP_VISUAL_REL_TYPES)

        with self.driver.session() as session:
            nodes_result = session.run(
                """
                MATCH (d:Document {id: $doc_id})

                OPTIONAL MATCH (d)-[r1]-(n1)
                WHERE NOT type(r1) IN $skip

                OPTIONAL MATCH (e:Experiment)-[:DESCRIBED_IN]->(d)
                OPTIONAL MATCH (e)-[:USES_MATERIAL]->(m:Material)
                OPTIONAL MATCH (e)-[:MEASURED]->(p:Property)
                OPTIONAL MATCH (e)-[:HAS_REGIME_PARAM]->(rp:RegimeParameter)
                OPTIONAL MATCH (e)-[:USES_PROCESS]->(pr:Process)

                WITH [x IN collect(DISTINCT d) + collect(DISTINCT n1)
                     + collect(DISTINCT e) + collect(DISTINCT m) + collect(DISTINCT p)
                     + collect(DISTINCT rp) + collect(DISTINCT pr) WHERE x IS NOT NULL] AS raw_nodes
                UNWIND raw_nodes AS node
                WITH DISTINCT node
                WHERE node IS NOT NULL
                RETURN node, labels(node)[0] AS label
                LIMIT $node_limit
                """,
                {"doc_id": document_id, "skip": skip, "node_limit": node_limit},
            )
            return self._build_visual_graph(session, nodes_result, edge_labels)

    def _collect_document_entity_nodes_subquery(self) -> str:
        """Cypher fragment: bind `d` to a Document, produce `raw_nodes` list."""
        return """
                MATCH (d:Document {id: $doc_id})
                OPTIONAL MATCH (d)-[r1]-(n1)
                WHERE NOT type(r1) IN $skip
                OPTIONAL MATCH (e:Experiment)-[:DESCRIBED_IN]->(d)
                OPTIONAL MATCH (e)-[:USES_MATERIAL]->(m:Material)
                OPTIONAL MATCH (e)-[:MEASURED]->(p:Property)
                OPTIONAL MATCH (e)-[:HAS_REGIME_PARAM]->(rp:RegimeParameter)
                OPTIONAL MATCH (e)-[:USES_PROCESS]->(pr:Process)
                WITH [x IN collect(DISTINCT n1) + collect(DISTINCT e) + collect(DISTINCT m)
                     + collect(DISTINCT p) + collect(DISTINCT rp) + collect(DISTINCT pr)
                     WHERE x IS NOT NULL] AS raw_nodes
        """

    def get_document_entity_summary(self, document_id: str) -> dict:
        """Fast per-type entity counts for hierarchical graph drill-down."""
        skip = list(SKIP_VISUAL_REL_TYPES)
        visual = list(VISUAL_NODE_LABELS) + ["Property", "RegimeParameter"]
        subquery = self._collect_document_entity_nodes_subquery()
        with self.driver.session() as session:
            rows = session.run(
                subquery
                + """
                UNWIND raw_nodes AS node
                WITH labels(node)[0] AS label, node
                WHERE label IN $visual
                RETURN label, count(DISTINCT node) AS count
                ORDER BY count DESC
                """,
                {"doc_id": document_id, "skip": skip, "visual": visual},
            )
            types = [{"label": r["label"], "count": int(r["count"])} for r in rows]
            total = sum(t["count"] for t in types)
            return {
                "document_id": document_id,
                "total_entities": total,
                "types": types,
            }

    def get_document_entities_by_type(
        self,
        document_id: str,
        entity_label: str,
        *,
        limit: int = 500,
        offset: int = 0,
    ) -> dict:
        """Paginated entities of one Neo4j label for a document."""
        allowed = set(VISUAL_NODE_LABELS) | {"Property", "RegimeParameter"}
        if entity_label not in allowed:
            return {
                "document_id": document_id,
                "entity_label": entity_label,
                "offset": offset,
                "limit": limit,
                "total": 0,
                "has_more": False,
                "nodes": [],
                "edges": [],
            }
        skip = list(SKIP_VISUAL_REL_TYPES)
        edge_labels = list(VISUAL_NODE_LABELS) + ["Property", "RegimeParameter"]
        subquery = self._collect_document_entity_nodes_subquery()
        with self.driver.session() as session:
            total_record = session.run(
                subquery
                + """
                UNWIND raw_nodes AS node
                WITH node WHERE labels(node)[0] = $entity_label
                RETURN count(DISTINCT node) AS total
                """,
                {
                    "doc_id": document_id,
                    "skip": skip,
                    "entity_label": entity_label,
                },
            ).single()
            total = int(total_record["total"]) if total_record else 0

            nodes_result = session.run(
                subquery
                + """
                UNWIND raw_nodes AS node
                WITH node WHERE labels(node)[0] = $entity_label
                WITH DISTINCT node
                ORDER BY toLower(
                    coalesce(node.name, node.title, node.regime_name, node.canonical_name, node.id)
                )
                SKIP $offset LIMIT $limit
                RETURN node, labels(node)[0] AS label
                """,
                {
                    "doc_id": document_id,
                    "skip": skip,
                    "entity_label": entity_label,
                    "offset": offset,
                    "limit": limit,
                },
            )
            graph = self._build_visual_graph(session, nodes_result, edge_labels)
            return {
                "document_id": document_id,
                "entity_label": entity_label,
                "offset": offset,
                "limit": limit,
                "total": total,
                "has_more": offset + limit < total,
                **graph,
            }

    def _build_visual_graph(self, session, nodes_result, edge_labels: list[str]) -> dict:
        """Turn a Neo4j node result set into React Flow / D3 payload."""
        rows = list(nodes_result)
        node_element_ids: list[str] = []
        experiment_element_ids: list[str] = []
        property_names: set[str] = set()

        for record in rows:
            node = record["node"]
            node_element_ids.append(node.element_id)
            node_labels = list(node.labels)
            if "Experiment" in node_labels:
                experiment_element_ids.append(node.element_id)
            canonical = dict(node).get("canonical_name")
            if "Property" in node_labels and canonical:
                property_names.add(str(canonical))

        property_values: dict[str, tuple[str, str]] = {}
        if experiment_element_ids:
            values_result = session.run(
                """
                MATCH (e:Experiment)-[r:MEASURED]->(p:Property)
                WHERE elementId(e) IN $eids
                  AND r.value IS NOT NULL AND r.value <> ''
                RETURN p.canonical_name AS name, r.value AS value, r.unit AS unit
                ORDER BY e.created_at DESC
                """,
                {"eids": experiment_element_ids},
            )
            for row in values_result:
                pname = row.get("name")
                if pname and pname not in property_values:
                    property_values[pname] = (str(row["value"]), str(row.get("unit") or ""))

        property_langs = self._load_property_languages(
            session,
            property_names=property_names or None,
        )

        nodes = []
        node_ids: set[str] = set()
        for record in rows:
            node = record["node"]
            node_id = self._visual_node_id(node)
            if not node_id or node_id in node_ids:
                continue
            node_labels = list(node.labels)
            canonical = dict(node).get("canonical_name")
            sample_value: str | None = None
            sample_unit: str | None = None
            if "Property" in node_labels and canonical and canonical in property_values:
                sample_value, sample_unit = property_values[canonical]
            nodes.append({
                "id": node_id,
                "label": self._visual_node_label(
                    node,
                    display_value=sample_value,
                    display_unit=sample_unit,
                    property_langs=property_langs,
                ),
                "type": record["label"],
                "properties": {
                    k: v for k, v in dict(node).items()
                    if k not in ("id", "title", "name", "canonical_name")
                },
            })
            if sample_value:
                nodes[-1]["properties"]["sample_value"] = sample_value
                if sample_unit:
                    nodes[-1]["properties"]["sample_unit"] = sample_unit
            node_ids.add(node_id)

        edges = []
        if node_element_ids:
            edges_result = session.run(
                """
                MATCH (a)-[r]->(b)
                WHERE elementId(a) IN $eids
                  AND elementId(b) IN $eids
                  AND NOT type(r) IN $skip
                RETURN a, b, type(r) AS type
                """,
                {
                    "eids": node_element_ids,
                    "skip": list(SKIP_VISUAL_REL_TYPES),
                },
            )
            seen_edges: set[tuple[str, str, str]] = set()
            for record in edges_result:
                source = self._visual_node_id(record["a"])
                target = self._visual_node_id(record["b"])
                rel_type = record["type"]
                if not source or not target:
                    continue
                if source not in node_ids or target not in node_ids:
                    continue
                key = (source, target, rel_type)
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                edges.append({
                    "source": source,
                    "target": target,
                    "type": rel_type,
                })

        return {"nodes": nodes, "edges": edges}

    def _build_visual_graph_for_entity_page(
        self,
        session,
        nodes_result,
        edge_labels: list[str],
        *,
        document_id: str,
        max_neighbors: int = 300,
    ) -> dict:
        """Entity page subgraph: typed nodes plus 1-hop document neighbors and edges."""
        rows = list(nodes_result)
        if not rows:
            return {"nodes": [], "edges": []}

        seed_eids: list[str] = []
        for record in rows:
            seed_eids.append(record["node"].element_id)

        skip = list(SKIP_VISUAL_REL_TYPES)
        neighbor_rows: list = []
        seen_eids = set(seed_eids)

        edge_records = list(
            session.run(
                """
                MATCH (a)-[r]-(b)
                WHERE elementId(a) IN $eids
                  AND NOT type(r) IN $skip
                  AND (
                    elementId(b) IN $eids
                    OR EXISTS { MATCH (d:Document {id: $doc_id})-[]-(b) }
                  )
                RETURN a, b, type(r) AS type
                LIMIT 8000
                """,
                {"eids": seed_eids, "skip": skip, "doc_id": document_id},
            )
        )

        neighbor_eids: list[str] = []
        for record in edge_records:
            for key in ("a", "b"):
                node = record[key]
                eid = node.element_id
                if eid in seen_eids:
                    continue
                seen_eids.add(eid)
                neighbor_eids.append(eid)
                if len(neighbor_eids) >= max_neighbors:
                    break
            if len(neighbor_eids) >= max_neighbors:
                break

        if neighbor_eids:
            neighbor_rows = list(
                session.run(
                    """
                    UNWIND $eids AS eid
                    MATCH (n)
                    WHERE elementId(n) = eid
                    RETURN n AS node, labels(n)[0] AS label
                    """,
                    {"eids": neighbor_eids},
                )
            )

        combined_rows = rows + neighbor_rows
        graph = self._build_visual_graph(session, combined_rows, edge_labels)

        if not edge_records:
            return graph

        node_ids = {n["id"] for n in graph["nodes"]}
        seen_edges: set[tuple[str, str, str]] = {
            (e["source"], e["target"], e["type"]) for e in graph["edges"]
        }
        for record in edge_records:
            source = self._visual_node_id(record["a"])
            target = self._visual_node_id(record["b"])
            rel_type = record["type"]
            if not source or not target:
                continue
            if source not in node_ids or target not in node_ids:
                continue
            key = (source, target, rel_type)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            graph["edges"].append(
                {"source": source, "target": target, "type": rel_type}
            )

        return graph

    def find_material_id_by_canonical_key(self, canonical_key: str) -> str | None:
        if not canonical_key:
            return None
        with self.driver.session() as session:
            record = session.run(
                """
                MATCH (m:Material)
                WHERE m.canonical_key = $key
                   OR coalesce(m.canonical_key, '') = ''
                      AND toLower(trim(m.name)) = toLower(trim($name))
                RETURN m.id AS id
                LIMIT 1
                """,
                {"key": canonical_key, "name": canonical_key.replace("_", " ")},
            ).single()
            return str(record["id"]) if record else None

    def find_similar_materials(self, name: str, limit: int = 20) -> list[dict]:
        """Ищет похожие материалы (для Entity Resolution)."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (m:Material)
                WHERE toLower(m.name) CONTAINS toLower($name)
                   OR any(alias IN m.aliases WHERE toLower(alias) CONTAINS toLower($name))
                RETURN m.id as id, m.name as name, m.aliases as aliases
                LIMIT $limit
            """, {"name": name, "limit": limit})
            return [dict(r) for r in result]
    
    def list_material_dtos_for_document(self, document_id: str) -> list[MaterialDTO]:
        """All materials mentioned by a document (for material–process linking)."""
        from domain.enums import MaterialState

        materials: list[MaterialDTO] = []
        with self.driver.session() as session:
            result = session.run("""
                MATCH (d:Document {id: $id})-[:MENTIONS_MATERIAL]->(m:Material)
                RETURN m
                ORDER BY toLower(m.name)
            """, {"id": document_id})
            for record in result:
                node = dict(record["m"])
                state_raw = node.get("state", "solid")
                state = (
                    MaterialState(state_raw)
                    if state_raw in MaterialState._value2member_map_
                    else MaterialState.SOLID
                )
                source_doc = node.get("source_document_id")
                materials.append(MaterialDTO(
                    id=UUID(node["id"]),
                    name=node.get("name") or "Unknown",
                    aliases=list(node.get("aliases") or []),
                    material_class=coerce_material_class(
                        node.get("material_class"),
                        name=node.get("name") or "",
                    ),
                    state=state,
                    properties={},
                    source_document_id=UUID(source_doc) if source_doc else None,
                ))
        return materials

    def get_material_by_id(self, material_id: UUID) -> MaterialDTO | None:
        """Load a material node from Neo4j for merge during entity resolution."""
        from domain.enums import MaterialState

        with self.driver.session() as session:
            record = session.run(
                "MATCH (m:Material {id: $id}) RETURN m",
                {"id": str(material_id)},
            ).single()
            if not record:
                return None
            node = dict(record["m"])
            state_raw = node.get("state", "solid")
            state = (
                MaterialState(state_raw)
                if state_raw in MaterialState._value2member_map_
                else MaterialState.SOLID
            )
            source_doc = node.get("source_document_id")
            return MaterialDTO(
                id=UUID(node["id"]),
                name=node.get("name") or "Unknown",
                aliases=list(node.get("aliases") or []),
                material_class=coerce_material_class(
                    node.get("material_class"),
                    name=node.get("name") or "",
                ),
                state=state,
                properties={},
                source_document_id=UUID(source_doc) if source_doc else None,
            )
    
    def update_material(self, material: MaterialDTO):
        """Обновляет материал."""
        self.save_material(material)
    
    def find_experiments_by_material_and_regime(
        self,
        material_name: str,
        regime_type: str | None = None
    ) -> list[dict]:
        """Ищет эксперименты."""
        with self.driver.session() as session:
            query = """
                MATCH (e:Experiment)-[:USES_MATERIAL]->(m:Material)
                WHERE toLower(m.name) CONTAINS toLower($material_name)
            """
            params = {"material_name": material_name}
            
            if regime_type:
                query += " AND e.regime_type = $regime_type"
                params["regime_type"] = regime_type
            
            query += """
                OPTIONAL MATCH (e)-[:DESCRIBED_IN]->(d:Document)
                RETURN e.id as id, e.regime_name as regime,
                       m.name as material, d.title as document
                LIMIT 50
            """
            
            result = session.run(query, params)
            return [dict(record) for record in result]
    
    def find_data_gaps(self) -> list[dict]:
        """Находит пробелы в исследованиях."""
        labels = self._get_graph_labels()
        rel_types = self._get_relationship_types()

        if not labels.intersection({"Material", "Experiment", "Property"}):
            return []

        gaps = []
        
        with self.driver.session() as session:
            if (
                "Material" in labels
                and "Experiment" in labels
                and "USES_MATERIAL" in rel_types
            ):
                result = session.run("""
                    MATCH (m:Material)
                    WHERE NOT (m)<-[:USES_MATERIAL]-(:Experiment)
                    RETURN m.name as material, 'no_experiments' as gap_type
                """)
                for r in result:
                    gaps.append({
                        "material": r["material"],
                        "gap_type": r["gap_type"],
                        "description": f"Материал '{r['material']}' не имеет связанных экспериментов"
                    })
            
            if (
                "Material" in labels
                and "Property" in labels
                and "HAS_PROPERTY" in rel_types
            ):
                result = session.run("""
                    MATCH (m:Material)
                    WHERE NOT (m)-[:HAS_PROPERTY]->(:Property {category: 'mechanical'})
                    RETURN m.name as material
                    LIMIT 10
                """)
                for r in result:
                    gaps.append({
                        "material": r["material"],
                        "gap_type": "no_mechanical_properties",
                        "description": f"У материала '{r['material']}' не измерены механические свойства"
                    })
            
            if (
                "Experiment" in labels
                and "Property" in labels
                and "MEASURED" in rel_types
            ):
                result = session.run("""
                    MATCH (e:Experiment)
                    WHERE NOT (e)-[:MEASURED]->(:Property)
                    RETURN e.id as id, e.regime_name as regime
                    LIMIT 10
                """)
                for r in result:
                    gaps.append({
                        "experiment_id": r["id"],
                        "regime": r["regime"],
                        "gap_type": "no_measured_properties",
                        "description": f"В эксперименте '{r['regime']}' не зафиксированы измеренные свойства"
                    })
        
        return gaps
    
    def search_by_text(self, query: str, limit: int = 20) -> list[dict]:
        """Search nodes by string/list properties without coercing arrays via toString()."""
        terms = extract_search_terms(query, limit=12)
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n)
                WHERE
                    (n.title IS NOT NULL AND any(t IN $terms WHERE toLower(n.title) CONTAINS t))
                    OR (n.name IS NOT NULL AND any(t IN $terms WHERE toLower(n.name) CONTAINS t))
                    OR (n.canonical_name IS NOT NULL AND any(t IN $terms WHERE toLower(n.canonical_name) CONTAINS t))
                    OR (n.regime_name IS NOT NULL AND any(t IN $terms WHERE toLower(n.regime_name) CONTAINS t))
                    OR (n.file_path IS NOT NULL AND any(t IN $terms WHERE toLower(n.file_path) CONTAINS t))
                    OR any(a IN coalesce(n.authors, []) WHERE any(t IN $terms WHERE toLower(a) CONTAINS t))
                    OR any(c IN coalesce(n.conclusions, []) WHERE any(t IN $terms WHERE toLower(c) CONTAINS t))
                RETURN n, labels(n)[0] as type
                LIMIT $limit
            """, {"terms": terms or [query.lower()], "limit": limit})

            results = []
            for record in result:
                node = record["n"]
                results.append({
                    "id": node.get("id"),
                    "type": record["type"],
                    "label": node.get("name") or node.get("canonical_name") or node.get("title"),
                    "properties": dict(node),
                })
            return results

    def search_text_chunks(
        self,
        query: str,
        limit: int = 20,
        *,
        document_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[dict]:
        """Full-text search over stored document chunks in Neo4j."""
        terms = extract_search_terms(query, limit=16)
        params: dict = {"terms": terms or [query.lower()], "limit": limit * 3}
        with self.driver.session() as session:
            if document_id:
                result = session.run("""
                    MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:DocumentChunk)
                    WHERE any(t IN $terms WHERE toLower(c.text) CONTAINS t)
                    WITH c, d, size([t IN $terms WHERE toLower(c.text) CONTAINS t]) AS hits
                    RETURN c.id as id, c.text as text, d.id as document_id, d.title as title, hits
                    ORDER BY hits DESC, c.chunk_index ASC
                    LIMIT $limit
                """, {**params, "document_id": document_id})
            elif document_ids:
                result = session.run("""
                    MATCH (d:Document)-[:HAS_CHUNK]->(c:DocumentChunk)
                    WHERE d.id IN $document_ids
                      AND any(t IN $terms WHERE toLower(c.text) CONTAINS t)
                    WITH c, d, size([t IN $terms WHERE toLower(c.text) CONTAINS t]) AS hits
                    RETURN c.id as id, c.text as text, d.id as document_id, d.title as title, hits
                    ORDER BY hits DESC, c.chunk_index ASC
                    LIMIT $limit
                """, {**params, "document_ids": list(document_ids)})
            else:
                result = session.run("""
                    MATCH (d:Document)-[:HAS_CHUNK]->(c:DocumentChunk)
                    WHERE any(t IN $terms WHERE toLower(c.text) CONTAINS t)
                    WITH c, d, size([t IN $terms WHERE toLower(c.text) CONTAINS t]) AS hits
                    RETURN c.id as id, c.text as text, d.id as document_id, d.title as title, hits
                    ORDER BY hits DESC, c.chunk_index ASC
                    LIMIT $limit
                """, params)

            rows = [dict(record) for record in result]
            return rows[:limit]

    def get_chunks_by_pages(
        self,
        page_numbers: list[int],
        *,
        document_id: str | None = None,
        document_ids: list[str] | None = None,
        neighbor_pages: int = 1,
    ) -> list[dict]:
        """Fetch page-level chunks when the user cites specific pages."""
        if not page_numbers:
            return []

        expanded: set[int] = set()
        for page in page_numbers:
            for offset in range(-neighbor_pages, neighbor_pages + 1):
                candidate = page + offset
                if candidate > 0:
                    expanded.add(candidate)
        pages = sorted(expanded)

        params: dict = {"pages": pages}
        with self.driver.session() as session:
            if document_id:
                result = session.run(
                    """
                    MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:DocumentChunk)
                    WHERE c.page_number IN $pages
                    RETURN c.id AS id, c.text AS text, c.page_number AS page_number,
                           d.id AS document_id, d.title AS title
                    ORDER BY c.page_number ASC, c.chunk_index ASC
                    """,
                    {**params, "document_id": document_id},
                )
            elif document_ids:
                result = session.run(
                    """
                    MATCH (d:Document)-[:HAS_CHUNK]->(c:DocumentChunk)
                    WHERE d.id IN $document_ids AND c.page_number IN $pages
                    RETURN c.id AS id, c.text AS text, c.page_number AS page_number,
                           d.id AS document_id, d.title AS title
                    ORDER BY c.page_number ASC, c.chunk_index ASC
                    """,
                    {**params, "document_ids": list(document_ids)},
                )
            else:
                result = session.run(
                    """
                    MATCH (d:Document)-[:HAS_CHUNK]->(c:DocumentChunk)
                    WHERE c.page_number IN $pages
                    RETURN c.id AS id, c.text AS text, c.page_number AS page_number,
                           d.id AS document_id, d.title AS title
                    ORDER BY c.page_number ASC, c.chunk_index ASC
                    """,
                    params,
                )
            return [dict(record) for record in result]

    def structured_search(
        self,
        *,
        material: str | None = None,
        material_class: str | None = None,
        process: str | None = None,
        geography: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        property_name: str | None = None,
        value_min: float | None = None,
        value_max: float | None = None,
        limit: int = 50,
    ) -> dict:
        """Multi-parameter graph query for mining/metallurgy R&D map."""
        where: list[str] = []
        params: dict = {"limit": limit}

        if material:
            where.append(
                "toLower(m.name) CONTAINS toLower($material) "
                "OR any(a IN coalesce(m.aliases, []) WHERE toLower(a) CONTAINS toLower($material))"
            )
            params["material"] = material
        if material_class:
            taxonomy = get_material_taxonomy()
            expanded = taxonomy.expand_classes(material_class)
            where.append("m.material_class IN $material_classes")
            params["material_classes"] = expanded
        if process:
            where.append(
                "(toLower(coalesce(pr.name, '')) CONTAINS toLower($process) "
                "OR toLower(coalesce(e.regime_name, '')) CONTAINS toLower($process) "
                "OR toLower(coalesce(e.regime_type, '')) CONTAINS toLower($process))"
            )
            params["process"] = process
        if geography:
            geo = geography.lower().strip()
            if geo in ("domestic", "russia", "ru", "россия", "российск"):
                where.append(
                    "(toLower(coalesce(d.scope, '')) = 'domestic' "
                    "OR toLower(coalesce(d.country, '')) IN ['russia', 'ru', 'россия'])"
                )
            elif geo in ("international", "global", "foreign", "abroad"):
                where.append("toLower(coalesce(d.scope, '')) IN ['international', 'global']")
            else:
                where.append("toLower(coalesce(d.country, '')) CONTAINS toLower($geography)")
                params["geography"] = geography
        if year_from is not None:
            where.append("d.year >= $year_from")
            params["year_from"] = year_from
        if year_to is not None:
            where.append("d.year <= $year_to")
            params["year_to"] = year_to
        if property_name:
            where.append(
                "EXISTS { MATCH (e)-[:MEASURED]->(p:Property) "
                "WHERE toLower(p.canonical_name) CONTAINS toLower($property_name) }"
            )
            params["property_name"] = property_name

        where_clause = " AND ".join(where) if where else "true"

        with self.driver.session() as session:
            result = session.run(
                f"""
                MATCH (e:Experiment)-[:USES_MATERIAL]->(m:Material)
                OPTIONAL MATCH (e)-[:DESCRIBED_IN]->(d:Document)
                OPTIONAL MATCH (e)-[:USES_PROCESS]->(pr:Process)
                WHERE {where_clause}
                RETURN e.id AS experiment_id,
                       e.regime_name AS regime,
                       e.regime_type AS regime_type,
                       e.status AS status,
                       m.name AS material,
                       d.id AS document_id,
                       d.title AS document_title,
                       d.year AS year,
                       d.country AS country,
                       d.scope AS scope,
                       d.reliability AS reliability,
                       pr.name AS process
                ORDER BY coalesce(d.year, 0) DESC, e.regime_name
                LIMIT $limit
                """,
                params,
            )
            rows = [dict(r) for r in result]

        if value_min is not None or value_max is not None:
            rows = self._filter_rows_by_measured_value(
                rows, property_name, value_min, value_max
            )

        documents = []
        seen_docs: set[str] = set()
        for row in rows:
            doc_id = row.get("document_id")
            if doc_id and doc_id not in seen_docs:
                seen_docs.add(doc_id)
                documents.append({
                    "id": doc_id,
                    "title": row.get("document_title"),
                    "year": row.get("year"),
                    "country": row.get("country"),
                    "scope": row.get("scope"),
                    "reliability": row.get("reliability"),
                })

        return {
            "count": len(rows),
            "experiments": rows,
            "documents": documents,
            "filters_applied": {
                k: v for k, v in params.items() if k != "limit" and v is not None
            },
        }

    def _filter_rows_by_measured_value(
        self,
        rows: list[dict],
        property_name: str | None,
        value_min: float | None,
        value_max: float | None,
    ) -> list[dict]:
        if not rows:
            return rows
        exp_ids = [r["experiment_id"] for r in rows if r.get("experiment_id")]
        if not exp_ids:
            return rows

        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (e:Experiment)-[r:MEASURED]->(p:Property)
                WHERE e.id IN $ids
                  AND ($property_name IS NULL
                       OR toLower(p.canonical_name) CONTAINS toLower($property_name))
                RETURN e.id AS experiment_id, r.value AS value
                """,
                {"ids": exp_ids, "property_name": property_name},
            )
            allowed: set[str] = set()
            for record in result:
                try:
                    val = float(str(record["value"]).replace(",", ".").split()[0])
                except (TypeError, ValueError):
                    continue
                if value_min is not None and val < value_min:
                    continue
                if value_max is not None and val > value_max:
                    continue
                allowed.add(record["experiment_id"])

        if not allowed:
            return []
        return [r for r in rows if r.get("experiment_id") in allowed]

    def find_contradictions(self, limit: int = 30) -> list[dict]:
        """Conflicting measured values for the same material + property."""
        labels = self._get_graph_labels()
        if not {"Material", "Experiment", "Property"}.issubset(labels):
            return []

        contradictions: list[dict] = []
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (m:Material)<-[:USES_MATERIAL]-(e1:Experiment)-[r1:MEASURED]->(p:Property)
                MATCH (m)<-[:USES_MATERIAL]-(e2:Experiment)-[r2:MEASURED]->(p)
                WHERE e1.id < e2.id AND r1.value <> r2.value
                OPTIONAL MATCH (e1)-[:DESCRIBED_IN]->(d1:Document)
                OPTIONAL MATCH (e2)-[:DESCRIBED_IN]->(d2:Document)
                RETURN m.name AS material,
                       p.canonical_name AS property,
                       r1.value AS value_a,
                       r2.value AS value_b,
                       e1.regime_name AS experiment_a,
                       e2.regime_name AS experiment_b,
                       d1.title AS source_a,
                       d2.title AS source_b
                LIMIT $limit
                """,
                {"limit": limit},
            )
            for record in result:
                contradictions.append({
                    "material": record["material"],
                    "property": record["property"],
                    "value_a": record["value_a"],
                    "value_b": record["value_b"],
                    "experiment_a": record["experiment_a"],
                    "experiment_b": record["experiment_b"],
                    "source_a": record["source_a"],
                    "source_b": record["source_b"],
                    "description": (
                        f"Conflicting {record['property']} for {record['material']}: "
                        f"{record['value_a']} vs {record['value_b']}"
                    ),
                })
        return contradictions

    def reconcile_duplicate_entities(self) -> dict:
        """Merge duplicate entity nodes (materials, teams, experts, etc.)."""
        from ingestion.entity_dedupe import reconcile_duplicate_entities as run_dedupe

        with self.driver.session() as session:
            return run_dedupe(session)

    def export_json_ld(self, limit: int = 500) -> dict:
        """Export knowledge graph as JSON-LD for interoperability."""
        graph = self.get_full_graph(limit=limit)
        entities = []
        for node in graph["nodes"]:
            label = node["type"]
            schema_type = {
                "Document": "ScholarlyArticle",
                "Material": "DefinedTerm",
                "Experiment": "ResearchProject",
                "Team": "Organization",
                "Expert": "Person",
                "Facility": "Place",
                "Equipment": "Product",
                "Process": "DefinedTerm",
                "Property": "PropertyValue",
                "RegimeParameter": "QuantitativeValue",
            }.get(label, "Thing")
            entities.append({
                "@type": schema_type,
                "@id": f"urn:scientific-tangle:{node['id']}",
                "name": node["label"],
                "additionalType": label,
            })

        relations = []
        for edge in graph["edges"]:
            relations.append({
                "@type": "Relationship",
                "source": f"urn:scientific-tangle:{edge['source']}",
                "target": f"urn:scientific-tangle:{edge['target']}",
                "relationshipType": edge["type"],
            })

        return {
            "@context": {
                "@vocab": "https://schema.org/",
                "relationshipType": "https://schema.org/additionalProperty",
            },
            "@graph": entities + relations,
        }