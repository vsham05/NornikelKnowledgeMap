from types import SimpleNamespace

from ingestion.parsers.title_slide_extract import (
    extract_all_people_from_document,
    extract_authors_from_text,
    extract_numbered_people_from_text,
    looks_like_author_name,
)


def test_russian_author_labels():
    text = (
        "Ответственный исполнитель: Петров Иван Сергеевич\n"
        "Научный руководитель: Сидорова Анна Владимировна"
    )
    names = extract_authors_from_text(text, 5000)
    assert any("Петров" in n for n in names)
    assert any("Сидорова" in n for n in names)


def test_numbered_roster_without_heading():
    text = """
1. Иванов Петр Петрович – инженер
2. Смирнова Елена Александровна – исследователь
"""
    names = extract_numbered_people_from_text(text)
    assert len(names) >= 2


def test_initials_before_surname():
    assert looks_like_author_name("И. И. Иванов")
    assert looks_like_author_name("Петров И. С.")


def test_extract_all_people_from_chunks():
    chunks = [
        SimpleNamespace(text="Исполнители: Козлов Дмитрий Игоревич\nРАО «НОРИЛЬСКИЙ НИКЕЛЬ»"),
        SimpleNamespace(text="1. Волков Алексей Петрович – эксперт"),
    ]
    names = extract_all_people_from_document(chunks, [])
    assert any("Козлов" in n for n in names)
    assert any("Волков" in n for n in names)
