from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Temperature:
    """Температура с единицей измерения."""
    value: float
    unit: str = "°C"
    
    def to_celsius(self) -> float:
        """Конвертация в Цельсии."""
        if self.unit == "K":
            return self.value - 273.15
        elif self.unit == "°F":
            return (self.value - 32) * 5 / 9
        return self.value
    
    def __str__(self) -> str:
        return f"{self.value}{self.unit}"


@dataclass(frozen=True)
class Duration:
    """Длительность с единицей измерения."""
    value: float
    unit: str = "h"
    
    def to_hours(self) -> float:
        """Конвертация в часы."""
        if self.unit == "min":
            return self.value / 60
        elif self.unit == "s":
            return self.value / 3600
        return self.value
    
    def __str__(self) -> str:
        return f"{self.value} {self.unit}"


@dataclass(frozen=True)
class Concentration:
    """Концентрация элемента."""
    element: str
    mass_fraction_percent: float
    
    def __post_init__(self):
        if not 0 <= self.mass_fraction_percent <= 100:
            raise ValueError("Концентрация должна быть от 0 до 100%")