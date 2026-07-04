from ingestion.nlp.process_text_scan import (
    append_process_record,
    find_process_phrases_in_text,
    looks_like_process_label,
)


def test_fem_phrase_detected_ru():
    text = (
        "Для верификации использован метод конечных элементов "
        "и связи конечной жесткости в ослабленной зоне."
    )
    hits = find_process_phrases_in_text(text, "ru")
    keys = {h[0] for h in hits}
    assert "finite_element_method" in keys
    assert "finite_stiffness_links" in keys


def test_glossary_geotech_process():
    text = "Проведено численное моделирование тектонического разлома."
    hits = find_process_phrases_in_text(text, "ru")
    keys = {h[0] for h in hits}
    assert "numerical_modeling" in keys or "geotechnical_modeling" in keys


def test_append_process_dedupes():
    processes: list[dict] = []
    assert append_process_record(
        processes, name="метод конечных элементов", document_id="doc-1"
    )
    assert len(processes) == 1
    assert not append_process_record(
        processes, name="метод конечных элементов", document_id="doc-1"
    )
    assert len(processes) == 1


def test_rejects_placeholder_process():
    processes: list[dict] = []
    assert not append_process_record(processes, name="method", document_id="doc-1")
    assert not append_process_record(processes, name="base", document_id="doc-1")
    assert len(processes) == 0


def test_section_title_like_process():
    assert looks_like_process_label("Моделирование тектонических нарушений")
    assert looks_like_process_label("Finite element analysis")
    assert not looks_like_process_label("method")
