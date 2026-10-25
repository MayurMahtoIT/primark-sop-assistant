from app.ingestion.pipeline import parse_key


def test_valid_key():
    m = parse_key("sops/HS/ALL/HS-014_Fitting-Room-Safety_v3.pdf")
    assert (m.sop_id, m.version, m.department, m.country, m.ext) == ("HS-014", "3", "HS", "ALL", "pdf")
    assert m.title == "Fitting Room Safety"


def test_country_scoped_and_semver():
    m = parse_key("sops/OPS/GB/OPS-021_Cash-Office_v5.2.docx")
    assert m.country == "GB" and m.version == "5.2"


def test_invalid_keys_are_rejected():
    assert parse_key("sops/random.pdf") is None
    assert parse_key("sops/HS/ALL/HS-014_x_v3.exe") is None
    assert parse_key("other/HS/ALL/HS-014_x_v3.pdf") is None


def test_primark_dba_markdown_key():
    m = parse_key("sops/Primark/SOP-DB-001_table_or_view_does_not_exist.md")
    assert m is not None
    assert (m.sop_id, m.version, m.department, m.country, m.ext) == ("SOP-DB-001", "1.0", "DBA", "ALL", "md")
    assert m.title == "table or view does not exist"


def test_primark_dba_markdown_key_rejects_unsupported_extension():
    assert parse_key("sops/Primark/SOP-DB-001_example.exe") is None


def test_parse_dba_metadata_defaults_shared_environment():

    # The DBA path convention is parsed independently of document contents.
    m = parse_key("sops/Primark/SOP-DB-041_orchestrator_status_is_stale.md")
    assert m.department == "DBA"
    assert m.country == "ALL"
