"""CLI entrypoint for SOP ingestion.

Examples
  python -m app.ingestion --local-dir /data/sops                 # local folder (docker compose)
  python -m app.ingestion --local-dir ../sops/Primark            # Oracle DBA Markdown SOPs only
  python -m app.ingestion --prefix sops/                         # full re-index from S3
  python -m app.ingestion --s3-key sops/HS/ALL/HS-014_..._v3.pdf # single object (EventBridge trigger)
  python -m app.ingestion --delete-key sops/HS/ALL/HS-014_..._v3.pdf
"""

import argparse
import json
import logging
import sys
from collections.abc import Iterator
from pathlib import Path

from app.aws import clients
from app.config import get_settings
from app.ingestion.pipeline import Ingestor, IngestResult
from app.logging_conf import configure_logging
from app.rag.embeddings import Embedder
from app.rag.index import ensure_schema
from app.vectorstore import get_postgres_connection

logger = logging.getLogger("ingestion")


def _s3_items(s3, bucket: str, prefix: str) -> Iterator[tuple[str, str, bytes]]:
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("/"):
                continue
            body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            yield obj["Key"], f"s3://{bucket}/{obj['Key']}", body


def _local_items(root: Path) -> Iterator[tuple[str, str, bytes]]:
    root = root.resolve()
    # Preserve the repository's sops/Primark/... DBA key convention when the
    # operator points directly at the Primark folder; otherwise treat root as sops/.
    prefix = "sops/Primark/" if root.name.lower() == "primark" else "sops/"
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        key = prefix + path.relative_to(root).as_posix()
        yield key, f"file://{path}", path.read_bytes()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SOP ingestion")
    ap.add_argument("--bucket")
    ap.add_argument("--prefix", default="sops/")
    ap.add_argument("--s3-key")
    ap.add_argument("--delete-key")
    ap.add_argument("--local-dir")
    ap.add_argument("--force", action="store_true", help="re-embed even if content is unchanged")
    ap.add_argument(
        "--recreate-table",
        "--recreate-collection",
        dest="recreate_table",
        action="store_true",
        help="DANGEROUS: deletes all vectors in the table",
    )
    args = ap.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    bucket = args.bucket or settings.sop_bucket

    conn = get_postgres_connection(settings)
    try:
        ensure_schema(conn, settings, recreate=args.recreate_table)
        embedder = Embedder(
            settings.mesh_api_key,
            settings.mesh_base_url,
            settings.embedding_model_name,
            settings.embedding_dimensions,
        )
        ingestor = Ingestor(conn, embedder, settings)

        if args.delete_key:
            ingestor.withdraw(f"s3://{bucket}/{args.delete_key}")
            return 0

        if args.local_dir:
            items = _local_items(Path(args.local_dir))
        elif args.s3_key:
            s3 = clients.s3_client(settings)
            body = s3.get_object(Bucket=bucket, Key=args.s3_key)["Body"].read()
            items = iter([(args.s3_key, f"s3://{bucket}/{args.s3_key}", body)])
        else:
            items = _s3_items(clients.s3_client(settings), bucket, args.prefix)

        results: list[IngestResult] = []
        failures = 0
        for key, uri, data in items:
            try:
                results.append(ingestor.ingest(key, data, uri, force=args.force))
            except Exception:  # noqa: BLE001 - keep going, fail the task at the end
                failures += 1
                logger.exception("ingest_failed", extra={"ctx": {"key": key}})

        summary = {
            "indexed": sum(r.status == "indexed" for r in results),
            "unchanged": sum(r.status == "skipped_unchanged" for r in results),
            "invalid_key": sum(r.status == "skipped_invalid_key" for r in results),
            "chunks": sum(r.chunks for r in results),
            "failed": failures,
        }
        print(json.dumps(summary))
        return 1 if failures else 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
