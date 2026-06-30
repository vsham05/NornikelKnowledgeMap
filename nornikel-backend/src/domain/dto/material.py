from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field

from domain.enums import MaterialClass, MaterialState
from domain.dto.property_value import PropertyDTO


class MaterialDTO(BaseModel):
    """
    Материал с динамическими свойствами.
    
    Жесткие поля — только то, что всегда есть и нужно для идентификации.
    Все остальное — в словаре properties, структура определяется онтологией.
    """
    model_config = {"frozen": True}
    
    # === Идентификация (жесткие поля) ===
    id: UUID
    name: str = Field(..., description="Каноническое название")
    aliases: list[str] = Field(default_factory=list, description="Синонимы: Ti-6Al-4V, ВТ6, Grade 5")
    material_class: MaterialClass
    state: MaterialState = MaterialState.SOLID
    
    # === Динамические свойства ===
    # Ключ — canonical name свойства (из онтологии), значение — PropertyDTO
    properties: dict[str, PropertyDTO] = Field(
        default_factory=dict,
        description="""
        Динамический словарь свойств. Примеры:
        - "density": PropertyDTO(name="density", category="physical", value=4.43, unit="g/cm³")
        - "composition": PropertyDTO(name="composition", category="chemical", value={"Ti": 90, "Al": 6, "V": 4})
        - "melting_point": PropertyDTO(name="melting_point", category="thermal", value_min=1600, value_max=1700, unit="°C")
        - "ultimate_tensile_strength": PropertyDTO(name="...", category="mechanical", value=900, unit="MPa")
        """
    )
    
    # === Микроструктурные особенности ===
    # Отдельно, т.к. это не числовые свойства, а описания
    microstructure_features: list[str] = Field(
        default_factory=list,
        description="Особенности структуры: 'мартенситная', 'игольчатая', 'равноосные зерна'"
    )
    
    # === Метаданные ===
    source_document_id: UUID | None = None
    created_at: date = Field(default_factory=date.today)
    
    # === Удобные методы ===
    def get_property(self, name: str) -> PropertyDTO | None:
        """Получить свойство по имени."""
        return self.properties.get(name)
    
    def get_properties_by_category(self, category: str) -> dict[str, PropertyDTO]:
        """Получить все свойства категории."""
        return {
            name: prop for name, prop in self.properties.items()
            if prop.category == category
        }
    
    def get_composition(self) -> dict[str, float] | None:
        """Получить химический состав (быстрый доступ)."""
        comp_prop = self.properties.get("composition")
        if comp_prop and comp_prop.value.is_composition():
            return comp_prop.value.value
        return None
    
    def get_mechanical_properties(self) -> dict[str, PropertyDTO]:
        """Все механические свойства."""
        return self.get_properties_by_category("mechanical")
    
    def get_thermal_properties(self) -> dict[str, PropertyDTO]:
        """Все термические свойства."""
        return self.get_properties_by_category("thermal")
    
    def get_physical_properties(self) -> dict[str, PropertyDTO]:
        """Все физические свойства."""
        return self.get_properties_by_category("physical")
    
    def merge_with(self, other: "MaterialDTO") -> "MaterialDTO":
        """
        Объединяет два MaterialDTO (для Entity Resolution).
        Свойства из other дополняют/перезаписывают свойства self.
        """
        merged_properties = {**self.properties, **other.properties}
        merged_aliases = list(set(self.aliases + other.aliases))
        merged_microstructure = list(set(
            self.microstructure_features + other.microstructure_features
        ))
        
        return MaterialDTO(
            id=self.id,
            name=self.name,
            aliases=merged_aliases,
            material_class=self.material_class,
            state=self.state,
            properties=merged_properties,
            microstructure_features=merged_microstructure,
            source_document_id=self.source_document_id,
            created_at=self.created_at,
        )