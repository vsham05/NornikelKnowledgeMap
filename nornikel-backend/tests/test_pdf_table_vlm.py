from ingestion.parsers.pdf_table_extract import chunk_likely_missing_table_data
from ingestion.parsers.pdf_table_vlm import merge_table_into_chunk, normalize_vlm_table_markdown


def test_chunk_likely_missing_table_data_detects_caption_only():
    text = (
        "Table 1 Pre-pilot autoclave runs\n\n"
        "Table 2 Autoclave POX discharge underflow rheology data summary\n"
    )
    assert chunk_likely_missing_table_data(text) is True


def test_chunk_likely_missing_table_data_false_when_table_present():
    text = (
        "Table 2 Summary\n\n"
        "[TABLE]\nTable 2 Summary\n| A | B |\n| --- | --- |\n| 1 | 2 |\n[/TABLE]"
    )
    assert chunk_likely_missing_table_data(text) is False


def test_normalize_vlm_table_strips_fences():
    raw = """```markdown
| % wt. | Yield stress, Pa |
| --- | --- |
| 34 | 21 |
```"""
    md = normalize_vlm_table_markdown(raw, "Table 2")
    assert md.startswith("|")
    assert "34" in md and "21" in md


def test_merge_table_into_chunk_appends_block():
    merged = merge_table_into_chunk(
        "Intro text",
        "Table 2 Rheology summary",
        "| A | B |\n| --- | --- |\n| 34 | 21 |",
    )
    assert "[TABLE]" in merged
    assert "34 | 21" in merged
    assert merged.startswith("Intro text")
