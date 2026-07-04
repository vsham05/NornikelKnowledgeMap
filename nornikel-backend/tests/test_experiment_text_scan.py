from uuid import uuid4

from domain.dto.material import MaterialDTO
from domain.enums import MaterialClass, MaterialState
from ingestion.nlp.experiment_text_scan import (
    experiments_from_table_blocks,
    experiments_from_text_phrases,
    find_experiment_phrases_in_text,
    merge_experiments,
)


def test_verification_model_phrase():
    text = "Построена верификационная модель ослабленной зоны с модулем E = 210000 MPa."
    hits = find_experiment_phrases_in_text(text, "ru")
    keys = {h[0] for h in hits}
    assert "verification_model" in keys
    assert hits[0][3].get("elastic_modulus") is not None


def test_table_rows_become_experiments():
    text = """
[TABLE]
Таблица 1. Модули упругости
| Зона | E, MPa | ν |
| --- | --- | --- |
| Основная часть бруса | 210000 | 0.30 |
| Ослабленная зона | 50000 | 0.35 |
[/TABLE]
"""
    doc_id = uuid4()
    materials = [
        MaterialDTO(
            id=uuid4(),
            name="брус",
            material_class=MaterialClass.OTHER,
            state=MaterialState.SOLID,
            properties={},
            source_document_id=doc_id,
        )
    ]
    exps = experiments_from_table_blocks(text, doc_id, materials)
    assert len(exps) >= 2
    names = " ".join(e.regime.name or "" for e in exps).lower()
    assert "основная" in names or "210000" in str(exps[0].measured_properties)


def test_merge_dedupes_experiments():
    doc_id = uuid4()
    mat_id = uuid4()
    materials = [
        MaterialDTO(
            id=mat_id,
            name="steel",
            material_class=MaterialClass.OTHER,
            state=MaterialState.SOLID,
            properties={},
            source_document_id=doc_id,
        )
    ]
    text = "Верификационная модель и верификационная модель повтор."
    batch = experiments_from_text_phrases(text, doc_id, materials, "ru")
    merged = merge_experiments([], batch)
    assert len(merged) == 1
