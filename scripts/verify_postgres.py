"""Smoke-test Mesh API embeddings and PostgreSQL / pgvector similarity search round trip.

Run from repository root after installing requirements and starting PostgreSQL (or docker compose up -d postgres).
"""

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings
from app.rag.embeddings import Embedder
from app.vectorstore import get_postgres_connection


def main() -> int:
    settings = get_settings()
    test_table = f"smoke_test_{uuid.uuid4().hex[:8]}"
    conn = None
    created = False
    try:
        embedder = Embedder(
            settings.mesh_api_key,
            settings.mesh_base_url,
            settings.embedding_model_name,
            settings.embedding_dimensions,
        )
        text = "ORA-00942: table or view does not exist. Verify the object and approved grants."
        vector = embedder.embed(text)
        if len(vector) != settings.embedding_dimensions:
            raise RuntimeError(f"Expected {settings.embedding_dimensions}-dim vector, got {len(vector)}")
        print(f"Mesh embeddings: OK ({settings.embedding_model_name}, {len(vector)} dimensions)")

        conn = get_postgres_connection(settings)
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(
                f"""
                CREATE TABLE {test_table} (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    sop_id TEXT NOT NULL,
                    error_code TEXT NOT NULL,
                    status TEXT NOT NULL,
                    embedding vector({settings.embedding_dimensions}) NOT NULL
                );
                """
            )
            created = True

            cur.execute(
                f"""
                INSERT INTO {test_table} (id, text, sop_id, error_code, status, embedding)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                ("smoke-ora-00942", text, "SOP-DB-001", "ORA-00942", "active", vector),
            )
            conn.commit()

            cur.execute(
                f"""
                SELECT id, text, (1.0 - (embedding <=> %s::vector)) AS similarity
                FROM {test_table}
                ORDER BY embedding <=> %s::vector ASC
                LIMIT 1;
                """,
                (vector, vector),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("PostgreSQL pgvector query returned no results")
            row_id = row.get("id") if isinstance(row, dict) else row[0]
            if row_id != "smoke-ora-00942":
                raise RuntimeError(f"Expected 'smoke-ora-00942', got {row_id}")

        print(f"PostgreSQL pgvector: OK (host={settings.postgres_host}:{settings.postgres_port}, db={settings.postgres_db})")
        print("Round trip: OK (insert -> pgvector <=> cosine similarity query -> expected SOP chunk)")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"PostgreSQL smoke test failed: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if conn is not None and created:
            try:
                with conn.cursor() as cur:
                    cur.execute(f"DROP TABLE IF EXISTS {test_table};")
                conn.commit()
            except Exception:  # noqa: S110, BLE001
                pass
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
