from ingestion.parsers.pdf_table_extract import (
    ExtractedTable,
    _extract_plaintext_table_block,
    _grid_to_markdown,
    _normalize_cell,
    _page_likely_has_table,
    _table_quality_score,
    _words_to_grid,
    merge_page_text_and_tables,
)


def test_grid_to_markdown_preserves_columns():
    grid = [
        ["Group A", "", "Group B", ""],
        ["% wt.", "τyB, Pa", "% wt.", "τyB, Pa"],
        ["34", "21", "49", "28"],
        ["29", "12", "43", "17"],
    ]
    md = _grid_to_markdown(grid)
    assert "| Group A |  | Group B |  |" in md
    assert "| 34 | 21 | 49 | 28 |" in md
    assert md.count("|") >= 12


def test_normalize_cell_decodes_html_entities():
    assert _normalize_cell("5&amp;#45;7") == "5-7"
    assert _normalize_cell("Col1&lt;br&gt;text") == "Col1 text"


def test_quality_rejects_garbage_table():
    garbage = [
        ["Fres|hly produ|ced", "autoclav|e", "discharge|"],
        ["&lt;br&gt;", "Col2", "Col3"],
        ["", "", ""],
    ]
    score = _table_quality_score(garbage)
    assert score < 0.42

    good = [
        ["% wt.", "τyB, Pa", "% wt.", "τyB, Pa"],
        ["34", "21", "49", "28"],
        ["29", "12", "43", "17"],
    ]
    assert _table_quality_score(good) >= 0.42


def test_page_likely_has_table_skips_prose():
    class ProsePage:
        def get_text(self, _mode):
            return "Introduction\n\nThis paper discusses hydrometallurgy and process design."

    assert _page_likely_has_table(ProsePage()) is False


def test_page_likely_has_table_detects_caption():
    class TablePage:
        def get_text(self, _mode):
            return "Results\n\nTable 2 Rheology summary for autoclave underflow\n34  21  49  28"

    assert _page_likely_has_table(TablePage()) is True


def test_plaintext_table_block_parses_spaced_numeric_rows():
    title = "Table 2 Autoclave POX discharge underflow rheology data summary"
    body = [
        "Option  % wt. solids  Yield stress, Pa  CSD, % wt.",
        "A       34           21                49",
        "A1      29           12                43",
        "B       28           17                41",
    ]
    table = _extract_plaintext_table_block(body, title)
    assert table is not None
    assert "34" in table.markdown
    assert "21" in table.markdown
    assert table.title == title


def test_words_to_grid_aligns_columns():
    words = [
        (72.0, 100.0, 95.0, 112.0, "34", 0, 0, 0),
        (150.0, 100.0, 170.0, 112.0, "21", 0, 0, 1),
        (240.0, 100.0, 260.0, 112.0, "49", 0, 0, 2),
        (280.0, 100.0, 300.0, 112.0, "28", 0, 0, 3),
        (72.0, 118.0, 95.0, 130.0, "29", 0, 1, 0),
        (150.0, 118.0, 170.0, 130.0, "12", 0, 1, 1),
        (240.0, 118.0, 260.0, 130.0, "43", 0, 1, 2),
        (280.0, 118.0, 300.0, 130.0, "17", 0, 1, 3),
    ]
    grid = _words_to_grid(words)
    md = _grid_to_markdown(grid)
    assert "| 34 | 21 | 49 | 28 |" in md
    assert "| 29 | 12 | 43 | 17 |" in md


def test_merge_page_text_and_tables_includes_markers():
    tables = [
        ExtractedTable(
            bbox=(10, 100, 400, 300),
            markdown="| a | b |\n| --- | --- |\n| 1 | 2 |",
            title="Table 2 Rheology summary",
            quality=0.9,
        )
    ]

    class FakePage:
        def get_text(self, _mode):
            return {"blocks": []}

    merged = merge_page_text_and_tables(FakePage(), tables)
    assert "[TABLE]" in merged
    assert "[/TABLE]" in merged
    assert "Table 2 Rheology summary" in merged
    assert "| 1 | 2 |" in merged
