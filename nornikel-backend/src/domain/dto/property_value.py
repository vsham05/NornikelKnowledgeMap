from datetime import datetime
from decimal import Decimal
from uuid import UUID
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class PropertyValueDTO(BaseModel):
    """Универсальное значение свойства с единицами измерения."""
    model_config = {"frozen": True}
    
    # Значение может быть разным типом
    value: float | int | str | bool | list[float] | dict[str, float | str]
    unit: str | None = Field(None, description="Единица измерения (МПа, %, °C, HV...)")
    
    # Для диапазонных значений (температура плавления 1600-1700°C)
    value_min: float | None = None
    value_max: float | None = None
    
    # Условия измерения (при какой температуре, скорости и т.д.)
    conditions: dict[str, Any] = Field(
        default_factory=dict,
        description="Условия: {temperature_c: 20, strain_rate: 0.001}"
    )
    
    # Метаданные
    source_document_id: UUID | None = None
    source_page: int | None = None
    source_text: str | None = Field(None, description="Исходный текст, откуда извлечено")
    confidence: float = Field(1.0, ge=0, le=1, description="Уверенность извлечения")
    extracted_at: datetime = Field(default_factory=datetime.now)
    
    @model_validator(mode="after")
    def validate_range(self):
        """Проверяем корректность диапазона."""
        if self.value_min is not None and self.value_max is not None:
            if self.value_min > self.value_max:
                raise ValueError("value_min должен быть <= value_max")
        return self
    
    def is_range(self) -> bool:
        """Является ли значение диапазоном."""
        return self.value_min is not None and self.value_max is not None
    
    def is_scalar(self) -> bool:
        """Является ли значение скаляром."""
        return isinstance(self.value, (int, float)) and not self.is_range()
    
    def is_composition(self) -> bool:
        """Является ли химическим составом."""
        return isinstance(self.value, dict)
    
    def display(self) -> str:
        """Человекочитаемое представление."""
        if self.is_range():
            return f"{self.value_min}-{self.value_max} {self.unit or ''}".strip()
        if isinstance(self.value, dict):
            parts = [f"{k}: {v}%" for k, v in self.value.items()]
            return ", ".join(parts)
        if isinstance(self.value, list):
            return f"[{', '.join(map(str, self.value))}]"
        return f"{self.value} {self.unit or ''}".strip()


class PropertyDTO(BaseModel):
    """Именованное свойство материала или эксперимента."""
    model_config = {"frozen": True}
    
    name: str = Field(..., description="Название свойства (canonical)")
    category: str = Field(..., description="Категория: mechanical, thermal, chemical, physical, microstructure")
    value: PropertyValueDTO
    aliases: list[str] = Field(default_factory=list, description="Синонимы из текста")
    
    def display(self) -> str:
        return f"{self.name}: {self.value.display()}"