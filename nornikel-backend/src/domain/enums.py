from enum import Enum


class MaterialClass(str, Enum):
    """Класс материала."""
    ALLOY = "alloy"
    CERAMIC = "ceramic"
    POLYMER = "polymer"
    COMPOSITE = "composite"
    OTHER = "other"


class MaterialState(str, Enum):
    """Состояние материала."""
    SOLID = "solid"
    LIQUID = "liquid"
    POWDER = "powder"
    FILM = "film"


class RegimeType(str, Enum):
    """Тип режима обработки."""
    HEAT_TREATMENT = "heat_treatment"
    MECHANICAL = "mechanical"
    CHEMICAL = "chemical"
    THERMOMECHANICAL = "thermomechanical"
    OTHER = "other"


class PropertyUnit(str, Enum):
    """Единицы измерения свойств."""
    MPa = "MPa"
    GPa = "GPa"
    PERCENT = "%"
    HV = "HV"  # Твердость по Виккерсу
    J_CM2 = "J/cm²"
    MM = "mm"
    UM = "μm"
    NM = "nm"
    CELSIUS = "°C"
    HOUR = "h"
    MINUTE = "min"


class ImageType(str, Enum):
    """Тип изображения."""
    MICROSTRUCTURE = "microstructure"
    PLOT = "plot"
    SCHEME = "scheme"
    TABLE = "table"
    OTHER = "other"


class DocumentType(str, Enum):
    """Тип документа."""
    ARTICLE = "article"
    REPORT = "report"
    PATENT = "patent"
    THESIS = "thesis"
    OTHER = "other"