"""Smoke-test Mesh API embeddings, generation, and PostgreSQL / pgvector connection."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings
from app.rag.embeddings import Embedder
from app.rag.index import ensure_schema
from app.rag.llm import LLM
from app.vectorstore import get_postgres_connection


def main() -> int:
    settings = get_settings()
    failed = False
    try:
        embedder = Embedder(
            settings.mesh_api_key,
            settings.mesh_base_url,
            settings.embedding_model_name,
            settings.embedding_dimensions,
        )
        vector = embedder.embed("ORA-00942: table or view does not exist")
        print(f"Mesh embeddings: OK (model={settings.embedding_model_name}, dimensions={len(vector)})")
    except Exception as exc:  # noqa: BLE001
        print(f"Mesh embeddings failed: {type(exc).__name__}: {exc}")
        return 1

    try:
        llm = LLM(
            settings.mesh_api_key,
            settings.mesh_base_url,
            settings.generation_model_id,
            settings.max_output_tokens,
            settings.temperature,
        )
        answer, usage = llm.generate(
            "Answer briefly.",
            [{"role": "user", "content": "Reply with OK only."}],
            max_tokens=16,
        )
        print(
            f"Mesh generation: OK (model={settings.generation_model_id}, "
            f"input_tokens={usage.input_tokens}, output_tokens={usage.output_tokens}, answer={answer!r})"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Mesh generation failed: {type(exc).__name__}: {exc}")
        failed = True

    try:
        conn = get_postgres_connection(settings)
        ensure_schema(conn, settings)
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS cnt FROM {settings.postgres_table};")
            row = cur.fetchone()
            count = row.get("cnt") if isinstance(row, dict) else row[0]
        conn.close()
        print(
            f"PostgreSQL / pgvector: OK (table={settings.postgres_table!r}, "
            f"host={settings.postgres_host}, documents={count})"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"PostgreSQL connection failed: {type(exc).__name__}: {exc}")
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
