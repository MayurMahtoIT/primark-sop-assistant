"""Retrieval quality gate and benchmark for PostgreSQL/pgvector SOP retrieval.

Measures:
  - Hit@k (Success rate)
  - Recall@k (Proportion of expected SOPs retrieved)
  - Precision@k (Chunk-level signal-to-noise in LLM context)
  - SOP Precision@k (Unique relevant SOPs / k)
  - MRR@k (Mean Reciprocal Rank)
  - MAP@k (Mean Average Precision)

Usage:
  python -m eval.run_eval --k 5
  python -m eval.run_eval --eval-all-k
  python -m eval.run_eval --verbose
"""

import argparse
import json
from pathlib import Path

from app.config import get_settings
from app.rag.embeddings import Embedder
from app.rag.index import ensure_schema
from app.rag.retrieval import PostgresRetriever
from app.vectorstore import get_postgres_connection


def evaluate_at_k(
    rows: list[dict],
    vectors: list[list[float]],
    retriever: PostgresRetriever,
    k: int,
    verbose: bool = False,
) -> dict:
    hits = 0
    recalls: list[float] = []
    chunk_precisions: list[float] = []
    sop_precisions: list[float] = []
    reciprocal_ranks: list[float] = []
    average_precisions: list[float] = []

    missed_queries = []

    for idx, (row, vector) in enumerate(zip(rows, vectors, strict=True), start=1):
        query = row["q"]
        country = row.get("country")
        department = row.get("department")

        # Ground truth set of SOP IDs
        expected_sops = set(row.get("expect_sops") or ([row["expect_sop"]] if "expect_sop" in row else []))

        ranked = retriever.search(
            query=query,
            vector=vector,
            department=department,
            country=country,
            top_k=k,
        )

        retrieved_chunk_sops = [chunk.sop_id for chunk in ranked]
        # Keep unique SOPs in retrieval order
        seen = set()
        retrieved_unique_sops = []
        for sid in retrieved_chunk_sops:
            if sid not in seen:
                seen.add(sid)
                retrieved_unique_sops.append(sid)

        # 1. Hit@k: Is at least one expected SOP in top-k?
        has_hit = any(sid in expected_sops for sid in retrieved_unique_sops)
        if has_hit:
            hits += 1
        else:
            missed_queries.append(
                {
                    "q": query,
                    "expected": list(expected_sops),
                    "retrieved": retrieved_unique_sops,
                }
            )

        # 2. Recall@k: |retrieved_unique ∩ expected| / |expected|
        relevant_retrieved = set(retrieved_unique_sops) & expected_sops
        rec = len(relevant_retrieved) / max(1, len(expected_sops))
        recalls.append(rec)

        # 3. Chunk Precision@k: relevant chunks in top-k / k
        relevant_chunks_count = sum(1 for sid in retrieved_chunk_sops if sid in expected_sops)
        chunk_prec = relevant_chunks_count / max(1, k)
        chunk_precisions.append(chunk_prec)

        # 4. SOP Precision@k: unique relevant SOPs / k
        sop_prec = len(relevant_retrieved) / max(1, k)
        sop_precisions.append(sop_prec)

        # 5. MRR@k: 1 / rank of first relevant SOP
        rr = 0.0
        for rank_idx, sid in enumerate(retrieved_unique_sops, start=1):
            if sid in expected_sops:
                rr = 1.0 / rank_idx
                break
        reciprocal_ranks.append(rr)

        # 6. MAP@k: Mean Average Precision
        score_sum = 0.0
        rel_count = 0
        for rank_idx, sid in enumerate(retrieved_unique_sops, start=1):
            if sid in expected_sops:
                rel_count += 1
                score_sum += rel_count / rank_idx
        ap = score_sum / max(1, len(expected_sops))
        average_precisions.append(ap)

        if verbose:
            status = "HIT" if has_hit else "MISS"
            print(
                f"[{status}] #{idx:02d} {query[:45]} -> Expect: {list(expected_sops)} | Got: {retrieved_unique_sops}"
            )

    n = max(1, len(rows))
    return {
        "k": k,
        "n_queries": len(rows),
        "hit_at_k": round(hits / n, 4),
        "recall_at_k": round(sum(recalls) / n, 4),
        "precision_at_k": round(sum(chunk_precisions) / n, 4),
        "sop_precision_at_k": round(sum(sop_precisions) / n, 4),
        "mrr_at_k": round(sum(reciprocal_ranks) / n, 4),
        "map_at_k": round(sum(average_precisions) / n, 4),
        "misses": missed_queries if verbose else len(missed_queries),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate PostgreSQL/pgvector SOP retrieval.")
    ap.add_argument("--k", type=int, default=5, help="Top-K cutoff to evaluate (default: 5)")
    ap.add_argument(
        "--eval-all-k",
        action="store_true",
        help="Evaluate at multiple cutoffs: k=1, k=3, k=5, k=10",
    )
    ap.add_argument("--min-hit", type=float, default=0.8, help="Minimum acceptable Hit@k threshold")
    ap.add_argument(
        "--min-recall",
        type=float,
        default=0.8,
        help="Minimum acceptable Recall@k threshold",
    )
    ap.add_argument("--verbose", action="store_true", help="Print detailed per-query evaluation")
    ap.add_argument(
        "--dataset",
        default=str(Path(__file__).parent / "golden_set.jsonl"),
        help="Path to golden dataset JSONL file",
    )
    args = ap.parse_args()

    settings = get_settings()
    conn = get_postgres_connection(settings)
    try:
        ensure_schema(conn, settings)
        embedder = Embedder(
            settings.mesh_api_key,
            settings.mesh_base_url,
            settings.embedding_model_name,
            settings.embedding_dimensions,
        )
        retriever = PostgresRetriever(
            conn,
            table=settings.postgres_table,
            max_per_sop=settings.max_chunks_per_sop,
            candidates=settings.retrieval_candidates,
        )

        rows = [
            json.loads(line)
            for line in Path(args.dataset).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS cnt FROM {settings.postgres_table};")
            count_res = cur.fetchone()
            total_count = count_res.get("cnt") if isinstance(count_res, dict) else count_res[0]

        print("=" * 60)
        print(" PRIMARK ORACLE DBA RAG RETRIEVAL EVALUATION")
        print("=" * 60)
        print(f" Database Table     : {settings.postgres_table} ({total_count} chunks indexed)")
        print(f" Embedding Model    : {settings.embedding_model_name} ({settings.embedding_dimensions}d)")
        print(f" Golden Test Cases  : {len(rows)} queries")
        print(" Embedding queries via Mesh API...")

        queries = [r["q"] for r in rows]
        vectors = embedder.embed_many(queries)
        print(f" Generated {len(vectors)} query embeddings successfully.")
        print("=" * 60)

        if args.eval_all_k:
            results = []
            for k_val in (1, 3, 5, 10):
                res = evaluate_at_k(rows, vectors, retriever, k_val, verbose=False)
                results.append(res)
            print("\nEvaluation Results Across Cutoffs:")
            print(
                f"{'k':<4} | {'Hit@k':<8} | {'Recall@k':<10} | {'Prec@k (Chunks)':<16} | {'Prec@k (SOP)':<14} | {'MRR@k':<8} | {'MAP@k':<8}"
            )
            print("-" * 80)
            for r in results:
                print(
                    f"{r['k']:<4} | {r['hit_at_k']:<8.4f} | {r['recall_at_k']:<10.4f} | {r['precision_at_k']:<16.4f} | {r['sop_precision_at_k']:<14.4f} | {r['mrr_at_k']:<8.4f} | {r['map_at_k']:<8.4f}"
                )
            primary_res = [r for r in results if r["k"] == args.k][0]
        else:
            primary_res = evaluate_at_k(rows, vectors, retriever, args.k, verbose=args.verbose)
            print(json.dumps(primary_res, indent=2))

        passed = primary_res["hit_at_k"] >= args.min_hit and primary_res["recall_at_k"] >= args.min_recall
        print("\n" + "=" * 60)
        print(
            f" Quality Gate (k={args.k}): {'PASSED' if passed else 'FAILED'} "
            f"(Hit@k: {primary_res['hit_at_k']:.2%}, Recall@k: {primary_res['recall_at_k']:.2%}, Prec@k: {primary_res['precision_at_k']:.2%})"
        )
        print("=" * 60)
        return 0 if passed else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
