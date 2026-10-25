from app.config import Settings
from app.ingestion.pipeline import Ingestor


class FakeEmbedder:
    def embed_many(self, texts):
        return [[float(len(text)), 1.0, 0.0] for text in texts]


class FakeCollection:
    def __init__(self):
        self.rows = {}

    def get(self, where=None, include=None):
        def matches(meta):
            if not where:
                return True
            if "$and" in where:
                return all(matches_clause(meta, part) for part in where["$and"])
            return matches_clause(meta, where)

        items = [(key, row) for key, row in self.rows.items() if matches(row["metadata"])]
        result = {"ids": [key for key, _ in items]}
        if include and "metadatas" in include:
            result["metadatas"] = [row["metadata"] for _, row in items]
        if include and "documents" in include:
            result["documents"] = [row["document"] for _, row in items]
        return result

    def upsert(self, ids, documents, embeddings, metadatas):
        for row_id, doc, vector, metadata in zip(ids, documents, embeddings, metadatas, strict=True):
            assert len(vector) == 3
            self.rows[row_id] = {"document": doc, "embedding": vector, "metadata": metadata}

    def delete(self, ids):
        for row_id in ids:
            self.rows.pop(row_id, None)

    def update(self, ids, metadatas):
        for row_id, metadata in zip(ids, metadatas, strict=True):
            self.rows[row_id]["metadata"] = metadata


def matches_clause(meta, clause):
    if "$and" in clause:
        return all(matches_clause(meta, part) for part in clause["$and"])
    for key, value in clause.items():
        expected = value.get("$eq") if isinstance(value, dict) else value
        if meta.get(key) != expected:
            return False
    return True


def test_ingests_oracle_markdown_and_is_idempotent():
    collection = FakeCollection()
    ingestor = Ingestor(collection, FakeEmbedder(), Settings())
    key = "sops/Primark/SOP-DB-001_table_or_view_does_not_exist.md"
    body = b"# Oracle DB SOP\n\nEnvironment: SIT3\n\nError Code: ORA-00942\n\n## Resolution\n\nCheck the object name and schema privileges. Use the approved DBA procedure."

    result = ingestor.ingest(key, body, "file://SOP-DB-001.md")
    assert result.status == "indexed"
    assert result.chunks >= 1
    assert all(row["metadata"]["error_code"] == "ORA-00942" for row in collection.rows.values())

    unchanged = ingestor.ingest(key, body, "file://SOP-DB-001.md")
    assert unchanged.status == "skipped_unchanged"
    assert len(collection.rows) == result.chunks


def test_ingest_postgres_executes_upsert_query():
    from unittest.mock import MagicMock

    mock_cursor = MagicMock()
    # First call for _already_indexed returns None (not yet indexed)
    mock_cursor.fetchone.return_value = None

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    ingestor = Ingestor(mock_conn, FakeEmbedder(), Settings())
    key = "sops/Primark/SOP-DB-001_table_or_view_does_not_exist.md"
    body = b"# Oracle DB SOP\n\nEnvironment: SIT3\n\nError Code: ORA-00942\n\n## Resolution\n\nCheck the object name and schema privileges. Use the approved DBA procedure."

    result = ingestor.ingest(key, body, "file://SOP-DB-001.md")
    assert result.status == "indexed"
    assert result.chunks >= 1
    assert mock_cursor.execute.called
    assert mock_conn.commit.called
