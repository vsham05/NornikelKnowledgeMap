from enum import Enum


class MaterialClass(str, Enum):
    """
    Process-material class along the mining → metallurgy value chain.
    Aligned with ISO TC 102/183 (ores & concentrates) and PMDco material entity types.
    """
    ORE = "ore"
    MINERAL = "mineral"
    CONCENTRATE = "concentrate"
    INTERMEDIATE = "intermediate"
    METAL = "metal"
    ALLOY = "alloy"
    SOLUTION = "solution"
    REAGENT = "reagent"
    COMPOUND = "compound"
    COMPOSITE = "composite"
    CERAMIC = "ceramic"
    POLYMER = "polymer"
    OTHER = "other"


class MaterialProcessStage(str, Enum):
    """Where the material sits in the process chain (derived from material_class)."""
    FEEDSTOCK = "feedstock"
    BENEFICIATION = "beneficiation"
    PROCESSING = "processing"
    PRODUCT = "product"
    ENGINEERING = "engineering"
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


class GeographyScope(str, Enum):
    """Domestic vs international practice."""
    DOMESTIC = "domestic"
    INTERNATIONAL = "international"
    GLOBAL = "global"


# Reliability weight for source verification (0–1)
DOCUMENT_RELIABILITY: dict[str, float] = {
    DocumentType.ARTICLE.value: 0.92,
    DocumentType.REPORT.value: 0.88,
    DocumentType.PATENT.value: 0.85,
    DocumentType.THESIS.value: 0.80,
    DocumentType.OTHER.value: 0.70,
}