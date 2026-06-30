from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from domain.enums import RegimeType
from domain.dto.property_value import PropertyDTO, PropertyValueDTO


class RegimeParameterDTO(BaseModel):
    """Параметр режима обработки (динамический)."""
    model_config = {"frozen": True}
    
    name: str = Field(..., description="Название параметра: temperature, duration, atmosphere")
    value: PropertyValueDTO
    
    def display(self) -> str:
        return f"{self.name}: {self.value.display()}"


class RegimeDTO(BaseModel):
    """
    Режим обработки — динамический набор параметров.
    
    Вместо жестких temperature_c, duration_hours — словарь параметров.
    Это позволяет описывать любые режимы: от простого нагрева до 
    сложной термо мехобработки с несколькими стадиями.
    """
    model_config = {"frozen": True}
    
    regime_type: RegimeType
    name: str | None = Field(None, description="Название: 'закалка', 'старение', 'отжиг'")
    
    # Динамические параметры режима
    parameters: dict[str, RegimeParameterDTO] = Field(
        default_factory=dict,
        description="""
        Примеры:
        - "temperature": RegimeParameterDTO(name="temperature", value=500, unit="°C")
        - "duration": RegimeParameterDTO(name="duration", value=2, unit="h")
        - "cooling_rate": RegimeParameterDTO(name="cooling_rate", value=10, unit="°C/min")
        - "atmosphere": RegimeParameterDTO(name="atmosphere", value="argon")
        - "deformation": RegimeParameterDTO(name="deformation", value=30, unit="%")
        """
    )
    
    # Описание текстом (если параметры не удалось структурировать)
    description: str | None = None
    
    def get_parameter(self, name: str) -> RegimeParameterDTO | None:
        return self.parameters.get(name)
    
    def get_temperature_c(self) -> float | None:
        """Быстрый доступ к температуре (частый кейс)."""
        temp = self.parameters.get("temperature")
        if temp and isinstance(temp.value.value, (int, float)):
            return float(temp.value.value)
        return None
    
    def get_duration_hours(self) -> float | None:
        """Быстрый доступ к длительности."""
        dur = self.parameters.get("duration")
        if dur and isinstance(dur.value.value, (int, float)):
            if dur.value.unit == "h":
                return float(dur.value.value)
            elif dur.value.unit == "min":
                return float(dur.value.value) / 60
        return None


class ExperimentDTO(BaseModel):
    """
    Эксперимент: материал + режим + измеренные свойства.
    
    Измеренные свойства — динамический словарь, как у MaterialDTO.
    """
    model_config = {"frozen": True}
    
    id: UUID
    material_id: UUID
    
    # Режим обработки
    regime: RegimeDTO
    
    # Динамические измеренные свойства
    measured_properties: dict[str, PropertyDTO] = Field(
        default_factory=dict,
        description="""
        Измеренные свойства в этом эксперименте:
        - "yield_strength": PropertyDTO(value=850, unit="MPa")
        - "elongation": PropertyDTO(value=12, unit="%")
        - "hardness": PropertyDTO(value=350, unit="HV")
        """
    )
    
    # Изменения свойств (если известна база/сравнение)
    property_changes: dict[str, PropertyValueDTO] = Field(
        default_factory=dict,
        description="""
        Относительные изменения:
        - "strength_delta_percent": PropertyValueDTO(value=15, unit="%")
        """
    )
    
    # Выводы эксперимента (текст)
    conclusions: list[str] = Field(default_factory=list)
    
    # Связи
    document_id: UUID
    image_ids: list[UUID] = Field(default_factory=list)
    
    # Метаданные
    created_at: datetime = Field(default_factory=datetime.now)
    
    def get_property(self, name: str) -> PropertyDTO | None:
        return self.measured_properties.get(name)
    
    def get_properties_by_category(self, category: str) -> dict[str, PropertyDTO]:
        return {
            name: prop for name, prop in self.measured_properties.items()
            if prop.category == category
        }