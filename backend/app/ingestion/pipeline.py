"""Ingest one SOP document: parse -> chunk -> embed -> bulk index -> retire old versions."""

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from app.config import Settings
from app.ingestion.chunking import chunk_sections
from app.ingestion.parsers import SUPPORTED_EXTENSIONS, parse_document
from app.rag.embeddings import Embedder

logger = logging.getLogger(__name__)

# sops/<DEPT>/<COUNTRY|ALL>/<SOP-ID>_<Title-With-Hyphens>_v<version>.<ext>
KEY_RE = re.compile(
    r"^sops/(?P<department>[A-Z]{2,5})/(?P<country>ALL|[A-Z]{2})/"
    r"(?P<sop_id>[A-Z]{2,5}-\d{3})_(?P<title>.+)_v(?P<version>\d+(?:\.\d+)*)\.(?P<ext>[A-Za-z0-9]+)$"
)
# Oracle DBA SOP pack: sops/Primark/SOP-DB-001_descriptive_title.md
DBA_KEY_RE = re.compile(
    r"^sops/Primark/(?P<sop_id>SOP-DB-\d{3})_(?P<title>.+)\.(?P<ext>[A-Za-z0-9]+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DocMeta:
    sop_id: str
    title: str
    version: str
    department: str
    country: str
    ext: str
    key: str


def parse_key(key: str) -> DocMeta | None:
    """Parse the original retail convention and the Oracle DBA SOP pack convention."""
    m = KEY_RE.match(key)
    if m:
        if m["ext"].lower() not in SUPPORTED_EXTENSIONS:
            return None
        return DocMeta(
            sop_id=m["sop_id"],
            title=m["title"].replace("-", " ").replace("_", " ").strip(),
            version=m["version"],
            department=m["department"],
            country=m["country"],
            ext=m["ext"].lower(),
            key=key,
        )

    dba = DBA_KEY_RE.match(key)
    if not dba or dba["ext"].lower() not in SUPPORTED_EXTENSIONS:
        return None
    return DocMeta(
        sop_id=dba["sop_id"].upper(),
        title=dba["title"].replace("-", " ").replace("_", " ").strip(),
        version="1.0",
        department="DBA",
        country="ALL",
        ext=dba["ext"].lower(),
        key=key,
    )


@dataclass
class IngestResult:
    key: str
    status: str  # indexed | skipped_unchanged | skipped_invalid_key
    chunks: int = 0


class Ingestor:
    def __init__(self, db_or_collection: Any, embedder: Embedder, settings: Settings):
        self._db = db_or_collection
        self._embedder = embedder
        self._settings = settings
        self._table = settings.postgres_table

    def _get_connection(self):
        if hasattr(self._db, "cursor"):
            from contextlib import nullcontext

            return nullcontext(self._db)
        if hasattr(self._db, "connection"):
            return self._db.connection()
        from contextlib import nullcontext

        return nullcontext(self._db)

    # --------------------------------------------------------------- upsert
    def ingest(self, key: str, data: bytes, source_uri: str, force: bool = False) -> IngestResult:
        meta = parse_key(key)
        if meta is None:
            logger.warning("ingest_skipped_invalid_key", extra={"ctx": {"key": key}})
            return IngestResult(key, "skipped_invalid_key")

        sha = hashlib.sha256(data).hexdigest()
        if not force and self._already_indexed(meta, sha):
            return IngestResult(key, "skipped_unchanged")

        chunks = chunk_sections(parse_document(data, meta.ext))
        if not chunks:
            raise ValueError(f"No extractable text in {key} (scanned PDF? run OCR first)")

        vectors = self._embedder.embed_many(
            [f"{meta.sop_id} {meta.title} > {c.section}\n{c.text}" for c in chunks]
        )
        now = datetime.now(UTC).isoformat()
        raw_text = data.decode("utf-8", errors="replace") if meta.ext in {"md", "txt"} else ""
        env_match = re.search(
            r"(?im)^\s*(?:[-*]\s*)?\*{0,2}Environment\s*:\s*\*{0,2}\s*`?([^`\n]+)", raw_text
        )
        environment = env_match.group(1).strip().strip("*") if env_match else "unspecified"
        error_match = re.search(r"(?i)\bORA-\d{5}\b", raw_text)
        error_code = error_match.group(0).upper() if error_match else ""

        # Check if running against PostgreSQL (has cursor or connection method)
        if hasattr(self._db, "cursor") or hasattr(self._db, "connection"):
            self._ingest_postgres(meta, chunks, vectors, sha, source_uri, environment, error_code, now)
        else:
            self._ingest_duck_typed(meta, chunks, vectors, sha, source_uri, environment, error_code, now)

        logger.info(
            "ingested", extra={"ctx": {"sop": meta.sop_id, "version": meta.version, "chunks": len(chunks)}}
        )
        return IngestResult(key, "indexed", len(chunks))

    def _ingest_postgres(
        self,
        meta: DocMeta,
        chunks,
        vectors,
        sha: str,
        source_uri: str,
        environment: str,
        error_code: str,
        now: str,
    ) -> None:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                ids = []
                insert_query = sql.SQL(
                    """
                    INSERT INTO {} (
                        id, chunk_id, sop_id, title, section, department, country,
                        environment, error_code, version, status, source_uri,
                        content_sha256, chunk_index, page, text, embedding, metadata, ingested_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, 'active', %s,
                        %s, %s, %s, %s, %s, %s::jsonb, %s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        section = EXCLUDED.section,
                        department = EXCLUDED.department,
                        country = EXCLUDED.country,
                        environment = EXCLUDED.environment,
                        error_code = EXCLUDED.error_code,
                        status = EXCLUDED.status,
                        source_uri = EXCLUDED.source_uri,
                        content_sha256 = EXCLUDED.content_sha256,
                        chunk_index = EXCLUDED.chunk_index,
                        page = EXCLUDED.page,
                        text = EXCLUDED.text,
                        embedding = EXCLUDED.embedding,
                        metadata = EXCLUDED.metadata,
                        ingested_at = EXCLUDED.ingested_at;
                    """
                ).format(sql.Identifier(self._table))

                for c, vec in zip(chunks, vectors, strict=True):
                    chunk_id = f"{meta.sop_id}:{meta.version}:{c.index}"
                    ids.append(chunk_id)
                    metadata_json = json.dumps(
                        {
                            "chunk_id": chunk_id,
                            "sop_id": meta.sop_id,
                            "title": meta.title,
                            "section": c.section,
                            "department": meta.department,
                            "country": meta.country,
                            "environment": environment,
                            "error_code": error_code,
                            "version": meta.version,
                            "page": c.page,
                        }
                    )
                    cur.execute(
                        insert_query,
                        (
                            chunk_id,
                            chunk_id,
                            meta.sop_id,
                            meta.title,
                            c.section,
                            meta.department,
                            meta.country,
                            environment,
                            error_code,
                            meta.version,
                            source_uri,
                            sha,
                            c.index,
                            c.page,
                            c.text,
                            vec,
                            metadata_json,
                            now,
                        ),
                    )

                # Delete stale chunks from the same version
                delete_query = sql.SQL(
                    "DELETE FROM {} WHERE sop_id = %s AND version = %s AND NOT (id = ANY(%s));"
                ).format(sql.Identifier(self._table))
                cur.execute(delete_query, (meta.sop_id, meta.version, ids))

                # Retire older active versions
                retire_query = sql.SQL(
                    "UPDATE {} SET status = 'superseded' WHERE sop_id = %s AND version != %s AND status = 'active';"
                ).format(sql.Identifier(self._table))
                cur.execute(retire_query, (meta.sop_id, meta.version))

            conn.commit()

    def _ingest_duck_typed(
        self,
        meta: DocMeta,
        chunks,
        vectors,
        sha: str,
        source_uri: str,
        environment: str,
        error_code: str,
        now: str,
    ) -> None:
        """Fallback for test fakes implementing upsert/get/delete/update."""
        ids = [f"{meta.sop_id}:{meta.version}:{c.index}" for c in chunks]
        metadatas = []
        for c in chunks:
            metadata = {
                "chunk_id": f"{meta.sop_id}:{meta.version}:{c.index}",
                "sop_id": meta.sop_id,
                "title": meta.title,
                "section": c.section,
                "department": meta.department,
                "country": meta.country,
                "environment": environment,
                "error_code": error_code,
                "version": meta.version,
                "status": "active",
                "source_uri": source_uri,
                "content_sha256": sha,
                "chunk_index": c.index,
                "ingested_at": now,
            }
            if c.page is not None:
                metadata["page"] = int(c.page)
            metadatas.append(metadata)

        self._db.upsert(
            ids=ids,
            documents=[c.text for c in chunks],
            embeddings=vectors,
            metadatas=metadatas,
        )

        previous = self._db.get(
            where={"$and": [{"sop_id": {"$eq": meta.sop_id}}, {"version": {"$eq": meta.version}}]},
            include=["metadatas"],
        )
        stale_ids = [item_id for item_id in previous.get("ids", []) if item_id not in ids]
        if stale_ids:
            self._db.delete(ids=stale_ids)

        all_sop_versions = self._db.get(
            where={"sop_id": {"$eq": meta.sop_id}},
            include=["metadatas"],
        )
        old_ids: list[str] = []
        old_metadata: list[dict] = []
        for item_id, item_metadata in zip(
            all_sop_versions.get("ids", []), all_sop_versions.get("metadatas", []), strict=False
        ):
            if (
                item_metadata
                and item_metadata.get("status") == "active"
                and item_metadata.get("version") != meta.version
            ):
                old_ids.append(item_id)
                old_metadata.append({**item_metadata, "status": "superseded"})
        if old_ids:
            self._db.update(ids=old_ids, metadatas=old_metadata)

    # --------------------------------------------------------------- delete
    def withdraw(self, source_uri: str) -> int:
        """SOP file deleted from S3 -> stop serving it immediately (kept for audit as 'withdrawn')."""
        if hasattr(self._db, "cursor") or hasattr(self._db, "connection"):
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    withdraw_query = sql.SQL(
                        "UPDATE {} SET status = 'withdrawn' WHERE source_uri = %s;"
                    ).format(sql.Identifier(self._table))
                    cur.execute(withdraw_query, (source_uri,))
                    count = cur.rowcount
                conn.commit()
            logger.info("withdrawn", extra={"ctx": {"source_uri": source_uri, "chunks": count}})
            return count

        found = self._db.get(where={"source_uri": {"$eq": source_uri}}, include=["metadatas"])
        ids = found.get("ids", [])
        metadatas = [
            {**metadata, "status": "withdrawn"} for metadata in found.get("metadatas", []) if metadata
        ]
        if ids and len(ids) == len(metadatas):
            self._db.update(ids=ids, metadatas=metadatas)
        logger.info("withdrawn", extra={"ctx": {"source_uri": source_uri, "chunks": len(ids)}})
        return len(ids)

    def _already_indexed(self, meta: DocMeta, sha: str) -> bool:
        if hasattr(self._db, "cursor") or hasattr(self._db, "connection"):
            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        check_query = sql.SQL(
                            """
                            SELECT 1 FROM {}
                            WHERE sop_id = %s AND version = %s AND content_sha256 = %s AND status = 'active'
                            LIMIT 1;
                            """
                        ).format(sql.Identifier(self._table))
                        cur.execute(check_query, (meta.sop_id, meta.version, sha))
                        return cur.fetchone() is not None
            except Exception:
                return False

        elif hasattr(self._db, "get"):
            resp = self._db.get(
                where={
                    "$and": [
                        {"sop_id": {"$eq": meta.sop_id}},
                        {"version": {"$eq": meta.version}},
                        {"content_sha256": {"$eq": sha}},
                        {"status": {"$eq": "active"}},
                    ]
                },
                include=["metadatas"],
            )
            return bool(resp.get("ids"))

        return False
