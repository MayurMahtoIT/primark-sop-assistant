from app.ingestion.chunking import chunk_sections
from app.ingestion.parsers import Section, parse_text


def test_sections_never_merge_and_keep_heading():
    secs = [
        Section("A", "Alpha text that is long enough to keep as a chunk."),
        Section("B", "Beta text that is long enough to keep as a chunk."),
    ]
    chunks = chunk_sections(secs)
    assert [c.section for c in chunks] == ["A", "B"]
    assert [c.index for c in chunks] == [0, 1]


def test_long_section_is_split_with_overlap():
    paras = [f"Paragraph {i}. " + "word " * 60 for i in range(12)]
    chunks = chunk_sections([Section("Long", "\n\n".join(paras))], max_chars=800, overlap_chars=350)
    assert len(chunks) > 1
    assert all(len(c.text) <= 800 + 350 for c in chunks)
    # overlap: the first paragraph of chunk n+1 appears at the end of chunk n
    first_of_next = chunks[1].text.split("\n\n")[0]
    assert first_of_next in chunks[0].text


def test_markdown_headings_become_sections():
    secs = parse_text(b"# Purpose\nWhy this exists.\n\n# Steps\n1. Do the thing carefully and log it.")
    assert [s.heading for s in secs] == ["Purpose", "Steps"]
