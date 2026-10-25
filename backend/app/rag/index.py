"""PostgreSQL schema and pgvector table setup. Safe to rerun."""

import logging
from typing import Any

from psycopg import sql

from app.config import Settings

logger = logging.getLogger(__name__)


def ensure_schema(pool_or_conn: Any, settings: Settings, recreate: bool = False) -> str:
    """Ensure the pgvector extension, table, and HNSW indexes exist.

    If recreate=True, the table is dropped and recreated.
    """
    table = settings.postgres_table
    dim = settings.embedding_dimensions

    # Accept either a ConnectionPool, a Connection, or a context-manager connection
    if hasattr(pool_or_conn, "cursor"):
        from contextlib import nullcontext

        cm = nullcontext(pool_or_conn)
    elif hasattr(pool_or_conn, "connection"):
        cm = pool_or_conn.connection()
    else:
        from contextlib import nullcontext

        cm = nullcontext(pool_or_conn)

    with cm as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            if recreate:
                cur.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE;").format(sql.Identifier(table)))
                logger.warning("postgres_table_dropped", extra={"ctx": {"table": table}})

            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {} (
                        id TEXT PRIMARY KEY,
                        chunk_id TEXT NOT NULL,
                        sop_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        section TEXT NOT NULL,
                        department TEXT NOT NULL,
                        country TEXT NOT NULL,
                        environment TEXT NOT NULL,
                        error_code TEXT NOT NULL,
                        version TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'active',
                        source_uri TEXT NOT NULL,
                        content_sha256 TEXT NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        page INTEGER,
                        text TEXT NOT NULL,
                        embedding vector({dim}) NOT NULL,
                        metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                ).format(sql.Identifier(table), dim=sql.Literal(dim))
            )

            # Check vector dimension if table already existed
            cur.execute(
                """
                SELECT atttypmod 
                FROM pg_attribute 
                WHERE attrelid = %s::regclass AND attname = 'embedding';
                """,
                (table,),
            )
            row = cur.fetchone()
            if row:
                typmod = row.get("atttypmod") if isinstance(row, dict) else row[0]
                if typmod and typmod > 0 and typmod != dim:
                    raise ValueError(
                        f"PostgreSQL table {table!r} has {typmod}-dimensional vector column; "
                        f"configured dimension is {dim}. Re-create the table or configure matching dimensions."
                    )

            # HNSW index for cosine distance similarity search (<=>)
            cur.execute(
                sql.SQL(
                    """
                    CREATE INDEX IF NOT EXISTS {} 
                    ON {} USING hnsw (embedding vector_cosine_ops);
                    """
                ).format(sql.Identifier(f"{table}_embedding_hnsw_idx"), sql.Identifier(table))
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (sop_id, status);").format(
                    sql.Identifier(f"{table}_sop_status_idx"), sql.Identifier(table)
                )
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (department, country);").format(
                    sql.Identifier(f"{table}_dept_country_idx"), sql.Identifier(table)
                )
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (error_code);").format(
                    sql.Identifier(f"{table}_error_code_idx"), sql.Identifier(table)
                )
            )

            cur.execute(sql.SQL("SELECT COUNT(*) AS cnt FROM {};").format(sql.Identifier(table)))
            count_row = cur.fetchone()
            count = count_row.get("cnt") if isinstance(count_row, dict) else count_row[0]

        conn.commit()

    logger.info("postgres_table_ready", extra={"ctx": {"table": table, "count": count}})
    return table


# Backward-compatible alias
ensure_collection = ensure_schema
