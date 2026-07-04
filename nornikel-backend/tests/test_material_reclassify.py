"""Material vs process/equipment classification heuristics."""

from ingestion.nlp.extraction_validate import (
    classify_non_material_entity,
    looks_like_concept_not_material,
)
from ingestion.nlp.document_enricher import DocumentEnricher
from domain.dto.material import MaterialDTO
from domain.enums import MaterialClass, MaterialState
from uuid import uuid4


def test_modeling_terms_are_not_materials():
    assert looks_like_concept_not_material("геометрическая модель")
    assert looks_like_concept_not_material("модуль упругости тектоники")
    assert looks_like_concept_not_material("калибровка параметров")
    assert looks_like_concept_not_material("integration into CAE")
    assert looks_like_concept_not_material("методика моделирования")


def test_real_substances_stay_materials():
    assert not looks_like_concept_not_material("rock")
    assert not looks_like_concept_not_material("granite")
    assert not looks_like_concept_not_material("гранит")
    assert classify_non_material_entity("руда") is None
    assert classify_non_material_entity("концентрат") is None
    assert classify_non_material_entity("ore") is None


def test_apparatus_mislabels_become_equipment():
    """Apparatus heads (not industry-specific pyromet regex)."""
    assert classify_non_material_entity("горелка концентрата") == "equipment"
    assert classify_non_material_entity("котел-утилизатор") == "equipment"
    assert classify_non_material_entity("pilot reactor") == "equipment"
    assert classify_non_material_entity("свод реакционной шахты") == "equipment"
    assert (
        classify_non_material_entity("отражательные перегородки в котле-утилизаторе")
        == "equipment"
    )


def test_operation_morphology_becomes_process():
    assert classify_non_material_entity("охлаждение печи") == "process"
    assert classify_non_material_entity("numerical modeling") == "process"
    assert classify_non_material_entity("sample preparation") == "process"
    assert classify_non_material_entity("подземная добыча") == "process"
    assert classify_non_material_entity("обогащения") == "process"
    assert classify_non_material_entity("закрытие рудника") == "process"


def test_non_substance_labels_are_not_materials():
    assert classify_non_material_entity("2004 год") == "temporal"
    assert classify_non_material_entity("2011 год") == "temporal"
    assert classify_non_material_entity("temperature") == "parameter"
    assert classify_non_material_entity("nickel_content") == "parameter"
    assert classify_non_material_entity("Dave Landriault") == "person"
    assert classify_non_material_entity("BHP") == "organization"
    assert classify_non_material_entity("Paterson&Cook") == "organization"
    assert classify_non_material_entity("Golder Associates") == "organization"
    assert classify_non_material_entity("Giant Mine") == "facility"
    assert classify_non_material_entity("Goldstrike Mine") == "facility"


def test_real_materials_still_valid():
    assert classify_non_material_entity("Fe2O3") is None
    assert classify_non_material_entity("slag • шлак") is None
    assert classify_non_material_entity("sulfuric acid • H2S") is None
    assert classify_non_material_entity("цемент") is None
    assert classify_non_material_entity("отходы обогащения") is None


def test_reclassify_material_dtos():
    doc_id = uuid4()
    materials = [
        MaterialDTO(
            id=uuid4(),
            name="печь",
            material_class=MaterialClass.OTHER,
            state=MaterialState.SOLID,
            properties={},
            source_document_id=doc_id,
        ),
        MaterialDTO(
            id=uuid4(),
            name="руда",
            material_class=MaterialClass.ORE,
            state=MaterialState.SOLID,
            properties={},
            source_document_id=doc_id,
        ),
    ]
    kept, procs, equip, facs = DocumentEnricher.reclassify_mislabeled_material_dtos(
        materials
    )
    assert len(kept) == 1
    assert kept[0].name == "руда"
    assert len(equip) == 1
    assert equip[0]["name"] == "печь"
    assert not procs
    assert not facs
