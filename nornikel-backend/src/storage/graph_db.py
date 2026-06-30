import logging
from uuid import UUID

from neo4j import AsyncGraphDatabase, GraphDatabase

from domain.dto.material import MaterialDTO
from domain.dto.experiment import ExperimentDTO
from domain.dto.document import DocumentDTO
from settings import Settings
from search.query_processing import extract_search_terms

logger = logging.getLogger(__name__)


class GraphDB:
    """Работа с Neo4j графовой БД."""
    
    def __init__(self, settings: Settings):
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password)
        )
        logger.info("Connected to Neo4j")
    
    def close(self):
        self.driver.close()

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
    
    def save_material(self, material: MaterialDTO):
        """Сохраняет материал с динамическими свойствами."""
        with self.driver.session() as session:
            # Создаем узел Material
            session.run("""
                MERGE (m:Material {id: $id})
                SET m.name = $name,
                    m.material_class = $material_class,
                    m.state = $state,
                    m.aliases = $aliases,
                    m.microstructure_features = $microstructure_features,
                    m.source_document_id = $source_document_id,
                    m.created_at = $created_at
            """, {
                "id": str(material.id),
                "name": material.name,
                "material_class": material.material_class.value,
                "state": material.state.value,
                "aliases": material.aliases,
                "microstructure_features": material.microstructure_features,
                "source_document_id": str(material.source_document_id) if material.source_document_id else None,
                "created_at": material.created_at.isoformat()
            })
            
            # Создаем узлы свойств и связи
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
                    "mat_id": str(material.id),
                    "name": prop_name,
                    "category": prop.category,
                    "unit": prop.value.unit,
                    "val_id": f"{str(material.id)}_{prop_name}",
                    "value": prop.value.value if not isinstance(prop.value.value, (dict, list)) else str(prop.value.value),
                    "value_min": prop.value.value_min,
                    "value_max": prop.value.value_max,
                    "conditions": prop.value.conditions,
                    "source_text": prop.value.source_text,
                    "confidence": prop.value.confidence
                })
        
        logger.info(f"Saved material: {material.name} ({len(material.properties)} properties)")
    
    def save_experiment(self, experiment: ExperimentDTO):
        """Сохраняет эксперимент."""
        with self.driver.session() as session:
            # Создаем узел Experiment
            regime_type = experiment.regime.regime_type.value
            regime_name = experiment.regime.name or regime_type
            
            session.run("""
                MERGE (e:Experiment {id: $id})
                SET e.regime_type = $regime_type,
                    e.regime_name = $regime_name,
                    e.regime_description = $regime_description,
                    e.conclusions = $conclusions,
                    e.document_id = $document_id,
                    e.created_at = $created_at
            """, {
                "id": str(experiment.id),
                "regime_type": regime_type,
                "regime_name": regime_name,
                "regime_description": experiment.regime.description,
                "conclusions": experiment.conclusions,
                "document_id": str(experiment.document_id),
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
    
    def save_document(self, document: DocumentDTO):
        """Сохраняет документ как узел в графе."""
        with self.driver.session() as session:
            session.run("""
                MERGE (d:Document {id: $id})
                SET d.title = $title,
                    d.document_type = $document_type,
                    d.authors = $authors,
                    d.year = $year,
                    d.file_path = $file_path,
                    d.content_hash = $content_hash,
                    d.canonical_source = $canonical_source,
                    d.file_hash = $file_hash,
                    d.chunks_count = $chunks_count,
                    d.images_count = $images_count,
                    d.created_at = $created_at
            """, {
                "id": str(document.id),
                "title": document.title,
                "document_type": document.document_type.value,
                "authors": document.authors,
                "year": document.year,
                "file_path": document.file_path,
                "content_hash": document.content_hash,
                "canonical_source": document.canonical_source,
                "file_hash": document.file_hash,
                "chunks_count": len(document.chunks),
                "images_count": len(document.images),
                "created_at": document.created_at.isoformat()
            })
            
            # Связь Material -> Document
            for image in document.images:
                session.run("""
                    MATCH (d:Document {id: $doc_id})
                    MERGE (i:Image {id: $img_id})
                    SET i.image_type = $image_type,
                        i.file_path = $file_path,
                        i.caption = $caption,
                        i.ai_description = $ai_description
                    MERGE (d)-[:CONTAINS_IMAGE]->(i)
                """, {
                    "doc_id": str(document.id),
                    "img_id": str(image.id),
                    "image_type": image.image_type.value,
                    "file_path": image.file_path,
                    "caption": image.caption,
                    "ai_description": image.ai_description
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
        """Remove a document and its chunks/images from the graph."""
        with self.driver.session() as session:
            exists = session.run(
                "MATCH (d:Document {id: $id}) RETURN d.id AS id",
                {"id": document_id},
            ).single()
            if not exists:
                return False

            session.run("""
                MATCH (d:Document {id: $id})
                OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:DocumentChunk)
                OPTIONAL MATCH (d)-[:CONTAINS_IMAGE]->(i:Image)
                DETACH DELETE c, i, d
            """, {"id": document_id})
            return True

    def list_documents(self, limit: int = 100) -> list[dict]:
        """List ingested documents."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (d:Document)
                OPTIONAL MATCH (d)-[:CONTAINS_IMAGE]->(i:Image)
                RETURN d.id as id, d.title as title,
                       d.document_type as document_type,
                       d.authors as authors,
                       d.year as year,
                       d.file_path as file_path,
                       d.chunks_count as chunks_count,
                       count(i) as images_count,
                       d.created_at as created_at
                ORDER BY d.created_at DESC
                LIMIT $limit
            """, {"limit": limit})
            return [dict(record) for record in result]

    # ================== READ (для API) ==================
    
    def get_stats(self) -> dict:
        """Общая статистика графа."""
        with self.driver.session() as session:
            counts = {}
            for label in ["Material", "Experiment", "Document", "Property", "Image", "RegimeParameter"]:
                result = session.run(f"MATCH (n:{label}) RETURN count(n) as c").single()
                counts[label.lower() + "s"] = result["c"]
            
            result = session.run("MATCH ()-[r]->() RETURN count(r) as c").single()
            counts["edges"] = result["c"]
            
            # Распределение классов материалов
            class_dist = {}
            result = session.run("""
                MATCH (m:Material) 
                RETURN m.material_class as cls, count(m) as c
            """)
            for record in result:
                class_dist[record["cls"]] = record["c"]
            counts["material_classes"] = class_dist
            
            # Распределение типов экспериментов
            regime_dist = {}
            result = session.run("""
                MATCH (e:Experiment) 
                RETURN e.regime_type as rt, count(e) as c
            """)
            for record in result:
                regime_dist[record["rt"]] = record["c"]
            counts["regime_types"] = regime_dist
            
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
    
    def get_full_graph(self, limit: int = 200) -> dict:
        """Document-level graph for visualization (excludes chunks/images)."""
        with self.driver.session() as session:
            nodes_result = session.run("""
                MATCH (d:Document)
                RETURN d as n, 'Document' as label
                ORDER BY coalesce(d.title, d.id)
                LIMIT $limit
            """, {"limit": limit})
            
            nodes = []
            node_ids = set()
            for record in nodes_result:
                node = record["n"]
                node_id = node.get("id")
                if not node_id:
                    continue
                nodes.append({
                    "id": node_id,
                    "label": node.get("title") or node.get("name") or node_id[:8],
                    "type": record["label"],
                    "properties": {k: v for k, v in dict(node).items() if k != "id"}
                })
                node_ids.add(node_id)
            
            edges = []
            if len(node_ids) > 1:
                edges_result = session.run("""
                    MATCH (a:Document)-[r]->(b:Document)
                    WHERE a.id IN $ids AND b.id IN $ids
                    RETURN a.id as source, b.id as target, type(r) as type
                """, {"ids": list(node_ids)})
                edges = [
                    {"source": r["source"], "target": r["target"], "type": r["type"]}
                    for r in edges_result
                ]
            
            return {"nodes": nodes, "edges": edges}
    
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
    
    def get_material_by_id(self, material_id: UUID) -> MaterialDTO | None:
        """Получает MaterialDTO по ID."""
        # TODO: Реализовать полную реконструкцию DTO из графа
        return None
    
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
    
    def get_coverage_matrix(self) -> dict:
        """Строит матрицу покрытия: материал × свойство."""
        labels = self._get_graph_labels()
        if "Material" not in labels:
            return {"materials": [], "properties": []}

        with self.driver.session() as session:
            result = session.run("""
                MATCH (m:Material)
                OPTIONAL MATCH (m)-[:HAS_PROPERTY]->(p:Property)
                WITH m, collect(DISTINCT p.canonical_name) as properties
                RETURN m.name as material, m.id as id, properties
                ORDER BY m.name
                LIMIT 100
            """)
            
            matrix = []
            all_properties = set()
            
            for record in result:
                props = record["properties"]
                all_properties.update(props)
                matrix.append({
                    "material": record["material"],
                    "material_id": record["id"],
                    "properties": props
                })
            
            return {
                "materials": matrix,
                "properties": sorted(all_properties)
            }
    
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

    def search_text_chunks(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search over stored document chunks in Neo4j."""
        terms = extract_search_terms(query, limit=12)
        with self.driver.session() as session:
            result = session.run("""
                MATCH (d:Document)-[:HAS_CHUNK]->(c:DocumentChunk)
                WHERE any(t IN $terms WHERE toLower(c.text) CONTAINS t)
                RETURN c.id as id, c.text as text, d.id as document_id, d.title as title
                LIMIT $limit
            """, {"terms": terms or [query.lower()], "limit": limit})

            return [dict(record) for record in result]