import logging
from difflib import SequenceMatcher
from uuid import UUID

from domain.dto.material import MaterialDTO
from domain.entity_glossary import canonical_entity_key
from storage.graph_db import GraphDB

logger = logging.getLogger(__name__)


class EntityResolver:
    """Разрешение сущностей — объединение дубликатов материалов."""
    
    def __init__(self, graph_db: GraphDB):
        self.graph_db = graph_db
    
    async def resolve_material(self, new_material: MaterialDTO) -> UUID:
        """
        Находит существующий материал или создает новый.
        
        Returns:
            UUID существующего или нового материала
        """
        key = canonical_entity_key(new_material.name)
        if key:
            existing_id = self.graph_db.find_material_id_by_canonical_key(key)
            if existing_id:
                existing = self.graph_db.get_material_by_id(UUID(existing_id))
                if existing:
                    merged = existing.merge_with(new_material).model_copy(
                        update={"id": UUID(existing_id)}
                    )
                    self.graph_db.save_material(merged)
                    logger.info("Canonical match: %s -> %s", new_material.name, existing_id)
                    return UUID(existing_id)

        existing_materials = self.graph_db.find_similar_materials(new_material.name)
        
        # Проверяем точное совпадение
        for existing in existing_materials:
            if self._is_exact_match(new_material.name, existing["name"]):
                logger.info(f"Exact match found: {new_material.name} -> {existing['id']}")
                return UUID(existing["id"])
        
        # Проверяем совпадение по алиасам
        for existing in existing_materials:
            if self._matches_alias(new_material, existing):
                logger.info(f"Alias match found: {new_material.name} -> {existing['id']}")
                return UUID(existing["id"])
        
        # Проверяем нечеткое сходство
        for existing in existing_materials:
            similarity = self._calculate_similarity(new_material.name, existing["name"])
            if similarity > 0.85:
                logger.info(f"Fuzzy match found ({similarity:.2f}): {new_material.name} -> {existing['id']}")
                return UUID(existing["id"])
        
        # Не нашли — создаем новый
        logger.info(f"Creating new material: {new_material.name}")
        resolved_id = self.graph_db.save_material(new_material)
        return UUID(resolved_id)
    
    def _is_exact_match(self, name1: str, name2: str) -> bool:
        """Проверяет точное совпадение (с нормализацией)."""
        norm1 = self._normalize_name(name1)
        norm2 = self._normalize_name(name2)
        return norm1 == norm2
    
    def _matches_alias(self, new_material: MaterialDTO, existing: dict) -> bool:
        """Проверяет совпадение по алиасам."""
        new_aliases = set(a.lower() for a in new_material.aliases)
        existing_aliases = set(a.lower() for a in existing.get("aliases", []))
        
        # Проверяем пересечение алиасов
        if new_aliases & existing_aliases:
            return True
        
        # Проверяем, что имя нового материала в алиасах существующего
        if new_material.name.lower() in existing_aliases:
            return True
        
        # Проверяем, что алиасы нового материала совпадают с именем существующего
        if existing["name"].lower() in new_aliases:
            return True
        
        return False
    
    def _calculate_similarity(self, name1: str, name2: str) -> float:
        """Вычисляет сходство строк (0-1)."""
        norm1 = self._normalize_name(name1)
        norm2 = self._normalize_name(name2)
        return SequenceMatcher(None, norm1, norm2).ratio()
    
    def _normalize_name(self, name: str) -> str:
        """Нормализует название материала."""
        key = canonical_entity_key(name)
        if key:
            return key
        return name.lower().replace(" ", "").replace("-", "")