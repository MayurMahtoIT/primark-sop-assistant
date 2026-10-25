"""PostgreSQL / pgvector connection pool factory and connection helpers."""

import logging

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import Settings

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


def _configure_connection(conn: psycopg.Connection) -> None:
    """Ensure pgvector extension is enabled before registering vector types."""
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.commit()
    except Exception:
        conn.rollback()
    register_vector(conn)


def get_connection_pool(settings: Settings) -> ConnectionPool:
    """Get or initialize the shared PostgreSQL connection pool with pgvector registered."""
    global _pool
    if _pool is None or _pool.closed:
        _pool = ConnectionPool(
            conninfo=settings.postgres_connection_string,
            min_size=1,
            max_size=10,
            timeout=30.0,
            configure=_configure_connection,
            kwargs={"row_factory": dict_row},
        )
    return _pool


def get_postgres_connection(settings: Settings) -> psycopg.Connection:
    """Open a standalone connection to PostgreSQL with pgvector registered (e.g. for CLI tasks)."""
    conn = psycopg.connect(
        settings.postgres_connection_string,
        row_factory=dict_row,
    )
    _configure_connection(conn)
    return conn


def close_connection_pool() -> None:
    """Close the connection pool cleanly on shutdown."""
    global _pool
    if _pool is not None and not _pool.closed:
        _pool.close()
        _pool = None
