from unittest.mock import MagicMock

from app.rag.retrieval import Chunk, PostgresRetriever, _where_conditions, diversify


def _matches(metadata, where):
    if "$and" in where:
        return all(_matches(metadata, item) for item in where["$and"])
    if "$or" in where:
        return any(_matches(metadata, item) for item in where["$or"])
    for key, condition in where.items():
        expected = condition.get("$eq") if isinstance(condition, dict) else condition
        if metadata.get(key) != expected:
            return False
    return True


class FakeCollection:
    def __init__(self, rows):
        self.rows = rows

    def count(self):
        return len(self.rows)

    def query(self, *, where, **kwargs):
        rows = [r for r in self.rows if _matches(r["metadata"], where)][: kwargs["n_results"]]
        return {
            "ids": [[r["id"] for r in rows]],
            "documents": [[r["document"] for r in rows]],
            "metadatas": [[r["metadata"] for r in rows]],
            "distances": [[r.get("distance", 0.2) for r in rows]],
        }

    def get(self, *, where, include):
        rows = [r for r in self.rows if _matches(r["metadata"], where)]
        out = {"ids": [r["id"] for r in rows]}
        if "documents" in include:
            out["documents"] = [r["document"] for r in rows]
        if "metadatas" in include:
            out["metadatas"] = [r["metadata"] for r in rows]
        return out


def _row(sop_id, chunk_index, text, error_code="", country="ALL", department="DBA", status="active"):
    return {
        "id": f"{sop_id}:1.0:{chunk_index}",
        "document": text,
        "distance": 0.25,
        "metadata": {
            "chunk_id": f"{sop_id}:1.0:{chunk_index}",
            "sop_id": sop_id,
            "title": text[:30],
            "section": "Resolution",
            "version": "1.0",
            "department": department,
            "country": country,
            "status": status,
            "error_code": error_code,
        },
    }


def test_filters_scope_active_department_and_country():
    where = _where_conditions("DBA", "GB")
    assert _matches({"status": "active", "department": "DBA", "country": "ALL"}, where)
    assert _matches({"status": "active", "department": "DBA", "country": "GB"}, where)
    assert not _matches({"status": "active", "department": "DBA", "country": "US"}, where)
    assert not _matches({"status": "superseded", "department": "DBA", "country": "ALL"}, where)


def test_exact_oracle_error_is_prioritized():
    collection = FakeCollection(
        [
            _row("SOP-DB-010", 0, "Network listener troubleshooting"),
            _row("SOP-DB-001", 0, "ORA-00942 table or view does not exist", "ORA-00942"),
        ]
    )
    retriever = PostgresRetriever(collection, max_per_sop=3, candidates=10)
    chunks = retriever.search(
        query="How do I fix ORA-00942?", vector=[0.0] * 384, department=None, country=None, top_k=5
    )
    assert chunks[0].sop_id == "SOP-DB-001"


def test_diversify_caps_chunks_per_sop():
    ranked = [Chunk(f"A:{i}", "A", "t", "s", "1", "DBA", "x", 1.0) for i in range(5)] + [
        Chunk("B:0", "B", "t", "s", "1", "DBA", "x", 0.9),
        Chunk("C:0", "C", "t", "s", "1", "DBA", "x", 0.8),
    ]
    out = diversify(ranked, top_k=5, max_per_sop=2)
    assert [chunk.sop_id for chunk in out] == ["A", "A", "B", "C"]


def test_postgres_retriever_executes_parameterized_query():
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {
            "id": "SOP-DB-001:1.0:0",
            "chunk_id": "SOP-DB-001:1.0:0",
            "sop_id": "SOP-DB-001",
            "title": "ORA-00942 Table Does Not Exist",
            "section": "Resolution",
            "department": "DBA",
            "country": "ALL",
            "environment": "SIT3",
            "error_code": "ORA-00942",
            "version": "1.0",
            "text": "Check schema permissions.",
            "page": 1,
            "metadata": {},
            "similarity": 0.85,
        }
    ]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    retriever = PostgresRetriever(mock_conn, table="sop_chunks", max_per_sop=3, candidates=10)
    chunks = retriever.search(
        query="How do I resolve ORA-00942?",
        vector=[0.1] * 1536,
        department="DBA",
        country="GB",
        top_k=5,
    )
    assert len(chunks) == 1
    assert chunks[0].sop_id == "SOP-DB-001"
    assert mock_cursor.execute.called
