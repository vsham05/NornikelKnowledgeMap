from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class PropertySchema(BaseModel):
    """Схема свойства из онтологии."""
    label: str
    category: str
    expected_units: list[str] = Field(default_factory=list)
    value_type: str  # scalar, range, dict, string, range_or_scalar
    range: tuple[float, float] | None = None
    examples: list[str] = Field(default_factory=list)


class RegimeParameterSchema(BaseModel):
    """Схема параметра режима."""
    label: str
    expected_units: list[str] = Field(default_factory=list)
    value_type: str
    range: tuple[float, float] | None = None
    examples: list[str] = Field(default_factory=list)


class RegimeTypeSchema(BaseModel):
    """Схема типа режима."""
    label: str
    parent: str | None = None
    typical_parameters: list[str] = Field(default_factory=list)


class MaterialClassSchema(BaseModel):
    """Process-material class in the mining/metallurgy value chain."""
    label: str
    label_ru: str | None = None
    stage: str = "other"
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    name_patterns: list[str] = Field(default_factory=list)


class Ontology(BaseModel):
    """Онтология системы — справочник всех возможных свойств и режимов."""
    property_categories: dict[str, dict[str, str]]
    properties: dict[str, PropertySchema]
    regime_parameters: dict[str, RegimeParameterSchema]
    regime_types: dict[str, RegimeTypeSchema]
    material_classes: dict[str, MaterialClassSchema] = Field(default_factory=dict)
    material_taxonomy_meta: dict[str, str] = Field(default_factory=dict)
    
    @classmethod
    def from_yaml(cls, path: Path) -> "Ontology":
        """Загружает онтологию из YAML файла."""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        # Парсим свойства
        properties = {}
        for name, prop_data in data.get("properties", {}).items():
            range_val = prop_data.get("range")
            if range_val:
                prop_data["range"] = tuple(range_val)
            properties[name] = PropertySchema(**prop_data)
        
        # Парсим параметры режимов
        regime_params = {}
        for name, param_data in data.get("regime_parameters", {}).items():
            range_val = param_data.get("range")
            if range_val:
                param_data["range"] = tuple(range_val)
            regime_params[name] = RegimeParameterSchema(**param_data)
        
        # Парсим типы режимов
        regime_types = {}
        for name, type_data in data.get("regime_types", {}).items():
            regime_types[name] = RegimeTypeSchema(**type_data)

        material_classes = {}
        for name, class_data in data.get("material_classes", {}).items():
            material_classes[name] = MaterialClassSchema(**class_data)
        
        return cls(
            property_categories=data.get("property_categories", {}),
            properties=properties,
            regime_parameters=regime_params,
            regime_types=regime_types,
            material_classes=material_classes,
            material_taxonomy_meta=data.get("material_taxonomy") or {},
        )
    
    def get_property_schema(self, name: str) -> PropertySchema | None:
        return self.properties.get(name)
    
    def get_all_property_names(self) -> list[str]:
        return list(self.properties.keys())
    
    def get_properties_by_category(self, category: str) -> dict[str, PropertySchema]:
        return {
            name: prop for name, prop in self.properties.items()
            if prop.category == category
        }
    
    def is_known_property(self, name: str) -> bool:
        return name in self.properties
    
    def get_expected_units(self, property_name: str) -> list[str]:
        """Возвращает ожидаемые единицы для свойства."""
        schema = self.properties.get(property_name)
        return schema.expected_units if schema else []

    def get_material_class_schema(self, class_id: str) -> MaterialClassSchema | None:
        return self.material_classes.get(class_id)

    def get_all_material_class_ids(self) -> list[str]:
        return list(self.material_classes.keys())


# Singleton
_ontology: Ontology | None = None


def get_ontology(configs_dir: Path | None = None) -> Ontology:
    """Получить онтологию (ленивая загрузка)."""
    global _ontology
    if _ontology is None:
        if configs_dir is None:
            from settings import get_settings
            configs_dir = get_settings().configs_dir
        _ontology = Ontology.from_yaml(configs_dir / "ontology.yaml")
    return _ontology