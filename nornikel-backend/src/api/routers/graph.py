"""Graph exploration endpoints — исследование графа знаний."""

import logging
from typing import Literal

from fastapi import APIRouter, Query, HTTPException, Depends

from api.deps import get_graph_db, get_ingestion_pipeline
from domain.dto.query import StructuredFiltersDTO
from domain.material_taxonomy import get_material_taxonomy
from ingestion.pipeline import IngestionPipeline
from storage.graph_db import GraphDB
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/graph", tags=["graph"])


# ================== Stats & Overview ==================

@router.get("/stats")
async def get_stats(graph_db: GraphDB = Depends(get_graph_db)):
    """
    Общая статистика графа:
    - Количество узлов по типам
    - Количество связей
    - Распределение материалов по классам
    - Распределение экспериментов по типам режимов
    """
    return graph_db.get_stats()


@router.post("/enrich-all")
async def enrich_all_documents(
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
):
    """
    Backfill Materials, Experiments, Processes, and Teams
    for documents that were ingested without graph entities.
    """
    return await pipeline.enrich_all_documents()


@router.post("/backfill-material-process-links")
async def backfill_material_process_links(
    document_id: str | None = Query(
        None, description="Single document id; omit to backfill all documents"
    ),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
):
    """Rebuild Material -> Process links from graph data (no LLM)."""
    return pipeline.backfill_material_process_links(document_id)


@router.get("/explore")
async def explore_graph(
    limit: int = Query(200, ge=1, le=1000, description="Max nodes to return"),
    graph_db: GraphDB = Depends(get_graph_db)
):
    """
    Получить граф для визуализации.
    
    Возвращает формат, совместимый с React Flow / D3:
    {
        "nodes": [{"id": "...", "label": "...", "type": "..."}],
        "edges": [{"source": "...", "target": "...", "type": "..."}]
    }
    """
    return graph_db.get_full_graph(limit=limit)


@router.get("/material-classes")
async def list_material_classes():
    """Process-material taxonomy for UI filters and extraction prompts."""
    taxonomy = get_material_taxonomy()
    classes = []
    for cls in taxonomy.all_classes():
        schema = taxonomy.get_schema(cls)
        classes.append({
            "id": cls.value,
            "label": schema.label if schema else cls.value,
            "stage": taxonomy.get_stage(cls).value,
            "description": schema.description if schema else "",
        })
    return {
        "taxonomy_version": taxonomy._ontology.material_taxonomy_meta.get("version", "1.0"),
        "classes": classes,
    }


@router.post("/query")
async def structured_graph_query(
    filters: StructuredFiltersDTO,
    limit: int = Query(50, ge=1, le=200),
    graph_db: GraphDB = Depends(get_graph_db),
):
    """
    Multi-parameter knowledge map query:
    material + process + geography + year range + numeric property limits.
    """
    return graph_db.structured_search(limit=limit, **filters.model_dump(exclude_none=True))


@router.get("/query")
async def structured_graph_query_get(
    material: str | None = None,
    material_class: str | None = None,
    process: str | None = None,
    geography: str | None = None,
    year_from: int | None = Query(None, ge=1900),
    year_to: int | None = Query(None, le=2100),
    property_name: str | None = None,
    value_min: float | None = None,
    value_max: float | None = None,
    limit: int = Query(50, ge=1, le=200),
    graph_db: GraphDB = Depends(get_graph_db),
):
    """GET variant for structured graph queries."""
    return graph_db.structured_search(
        material=material,
        material_class=material_class,
        process=process,
        geography=geography,
        year_from=year_from,
        year_to=year_to,
        property_name=property_name,
        value_min=value_min,
        value_max=value_max,
        limit=limit,
    )


@router.get("/export/json-ld")
async def export_json_ld(
    limit: int = Query(500, ge=10, le=2000),
    graph_db: GraphDB = Depends(get_graph_db),
):
    """Export knowledge graph as JSON-LD (FAIR / interoperability)."""
    return graph_db.export_json_ld(limit=limit)


@router.get("/analytics/contradictions")
async def get_contradictions(
    limit: int = Query(30, ge=1, le=100),
    graph_db: GraphDB = Depends(get_graph_db),
):
    """Conflicting measurements for the same material + property across sources."""
    items = graph_db.find_contradictions(limit=limit)
    return {"contradictions": items, "count": len(items)}

# ================== Materials ==================

@router.get("/materials")
async def list_materials(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    graph_db: GraphDB = Depends(get_graph_db)
):
    """Список всех материалов с количеством свойств и экспериментов."""
    materials = graph_db.list_materials(limit=limit, offset=offset)
    return {
        "materials": materials,
        "count": len(materials),
        "limit": limit,
        "offset": offset
    }


@router.get("/materials/{material_id}")
async def get_material(
    material_id: str,
    graph_db: GraphDB = Depends(get_graph_db)
):
    """
    Детальная информация о материале:
    - Все свойства (динамические)
    - Все связанные эксперименты
    - Ссылки на документы
    """
    material = graph_db.get_material_details(material_id)
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")
    return material


@router.get("/materials/{material_id}/subgraph")
async def get_material_subgraph(
    material_id: str,
    depth: int = Query(2, ge=1, le=4),
    max_nodes: int = Query(100, ge=10, le=500),
    graph_db: GraphDB = Depends(get_graph_db)
):
    """
    Подграф вокруг материала (для интерактивной визуализации).
    
    Показывает: материал → свойства, материал → эксперименты → режимы → документы
    """
    return graph_db.get_subgraph(material_id, depth=depth, max_nodes=max_nodes)


# ================== Experiments ==================

@router.get("/experiments")
async def list_experiments(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    graph_db: GraphDB = Depends(get_graph_db)
):
    """Список всех экспериментов."""
    experiments = graph_db.list_experiments(limit=limit, offset=offset)
    return {
        "experiments": experiments,
        "count": len(experiments),
        "limit": limit,
        "offset": offset
    }


@router.get("/experiments/{experiment_id}")
async def get_experiment(
    experiment_id: str,
    graph_db: GraphDB = Depends(get_graph_db)
):
    """
    Детали эксперимента:
    - Материал
    - Параметры режима
    - Измеренные свойства
    - Выводы
    - Документ-источник
    """
    experiment = graph_db.get_experiment_details(experiment_id)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiment


@router.get("/experiments/{experiment_id}/subgraph")
async def get_experiment_subgraph(
    experiment_id: str,
    depth: int = Query(2, ge=1, le=4),
    max_nodes: int = Query(100, ge=10, le=500),
    graph_db: GraphDB = Depends(get_graph_db)
):
    """Подграф вокруг эксперимента."""
    return graph_db.get_subgraph(experiment_id, depth=depth, max_nodes=max_nodes)


# ================== Search ==================

@router.get("/search")
async def search_graph(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    graph_db: GraphDB = Depends(get_graph_db)
):
    """
    Полнотекстовый поиск по узлам графа.
    
    Ищет по всем строковым полям узлов (name, title, description и т.д.).
    """
    results = graph_db.search_by_text(q, limit=limit)
    return {
        "query": q,
        "results": results,
        "count": len(results)
    }


@router.get("/experiments/by-material")
async def find_experiments_by_material(
    material: str = Query(..., description="Material name (partial match)"),
    regime_type: str | None = Query(None, description="Filter by regime type"),
    graph_db: GraphDB = Depends(get_graph_db)
):
    """
    Найти эксперименты по названию материала.
    
    Отвечает на вопрос: "что уже делали по сплавам X"
    """
    results = graph_db.find_experiments_by_material_and_regime(
        material_name=material,
        regime_type=regime_type
    )
    return {
        "material": material,
        "regime_type": regime_type,
        "experiments": results,
        "count": len(results)
    }


# ================== Analytics ==================

@router.get("/analytics/gaps")
async def get_data_gaps(graph_db: GraphDB = Depends(get_graph_db)):
    """
    Пробелы в исследованиях (Data Gaps):
    - Материалы без экспериментов
    - Материалы без механических свойств
    - Эксперименты без измеренных свойств
    """
    gaps = graph_db.find_data_gaps()
    return {
        "gaps": gaps,
        "count": len(gaps),
        "summary": {
            "materials_without_experiments": len([g for g in gaps if g["gap_type"] == "no_experiments"]),
            "materials_without_mechanical": len([g for g in gaps if g["gap_type"] == "no_mechanical_properties"]),
            "experiments_without_measurements": len([g for g in gaps if g["gap_type"] == "no_measured_properties"])
        }
    }


# ================== Properties ==================

@router.get("/properties")
async def list_properties(
    category: str | None = Query(None, description="Filter by category"),
    graph_db: GraphDB = Depends(get_graph_db)
):
    """Список всех уникальных свойств с статистикой."""
    with graph_db.driver.session() as session:
        query = """
            MATCH (p:Property)
            OPTIONAL MATCH (m:Material)-[:HAS_PROPERTY]->(p)
            OPTIONAL MATCH (e:Experiment)-[:MEASURED]->(p)
            WITH p, count(DISTINCT m) as materials_count, count(DISTINCT e) as experiments_count
        """
        
        if category:
            query += " WHERE p.category = $category"
            params = {"category": category}
        else:
            params = {}
        
        query += """
            RETURN p.canonical_name as name, p.category as category,
                   p.unit as unit, materials_count, experiments_count
            ORDER BY materials_count DESC, p.canonical_name
        """
        
        result = session.run(query, params)
        properties = [dict(r) for r in result]
    
    return {
        "properties": properties,
        "count": len(properties),
        "category_filter": category
    }


# ================== Regimes ==================

@router.get("/regimes")
async def list_regimes(graph_db: GraphDB = Depends(get_graph_db)):
    """Список всех уникальных режимов обработки."""
    with graph_db.driver.session() as session:
        result = session.run("""
            MATCH (e:Experiment)
            WITH e.regime_type as type, e.regime_name as name, count(e) as count
            RETURN type, name, count
            ORDER BY count DESC
        """)
        
        regimes = [dict(r) for r in result]
    
    return {
        "regimes": regimes,
        "count": len(regimes)
    }


# ================== Health ==================

@router.get("/health")
async def health_check(graph_db: GraphDB = Depends(get_graph_db)):
    """Проверка работоспособности графовой БД."""
    try:
        with graph_db.driver.session() as session:
            result = session.run("RETURN 1 as n").single()
            return {
                "status": "healthy",
                "neo4j": "connected",
                "test_query": result["n"]
            }
    except Exception as e:
        logger.error(f"Neo4j health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Neo4j unavailable: {str(e)}")