"""Graph exploration endpoints — исследование графа знаний."""

import logging
from typing import Literal

from fastapi import APIRouter, Query, HTTPException, Depends

from api.deps import get_graph_db, get_ingestion_pipeline
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
    Backfill Materials, Experiments, Modes (topics), and Teams
    for documents that were ingested without graph entities.
    """
    return await pipeline.enrich_all_documents()


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


@router.get("/analytics/coverage-matrix")
async def get_coverage_matrix(graph_db: GraphDB = Depends(get_graph_db)):
    """
    Матрица покрытия: материал × свойство.
    
    Показывает, какие свойства измерены для каких материалов.
    Пустые ячейки = пробелы в данных.
    """
    return graph_db.get_coverage_matrix()


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