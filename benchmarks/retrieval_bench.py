#!/usr/bin/env python3
"""
tripartite-memory — Distilled Knowledge Retrieval Benchmark
=============================================================

Tests Recall@1 and Recall@5 on a 30-document corpus of engineering
constraints using tripartite-memory's recall() as the retrieval backend.

The corpus covers cross-cutting operational knowledge: concurrency patterns,
database gotchas, security pipelines, process isolation, and lifecycle
state management. QA pairs are paraphrased — query wording deliberately
avoids the exact vocabulary in the source document, testing semantic
retrieval rather than keyword matching.

Requirements:
    pip install tripartite-memory
    # Running Qdrant and Ollama (nomic-embed-text) — see README

Usage:
    python benchmarks/retrieval_bench.py
    python benchmarks/retrieval_bench.py --top-k 5
    python benchmarks/retrieval_bench.py --verbose
    python benchmarks/retrieval_bench.py --collection my_collection

Reported baseline (tripartite-memory v0.2.1, nomic-embed-text):
    R@1 = 80.0%   R@5 = 100.0%   (n=30)
"""

import asyncio
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from corpus import ENTRIES, QA_PAIRS

BENCH_COLLECTION = "distilled_knowledge_bench"


async def ingest_corpus(memory, collection: str, verbose: bool) -> None:
    for fname, text in ENTRIES:
        await memory.ingest(
            content=text,
            actor="benchmark:retrieval_bench",
            tags=["benchmark", "distilled_knowledge"],
            collection=collection,
        )
        if verbose:
            print(f"  ingested {fname}", flush=True)


async def run_async(top_k: int, collection: str, verbose: bool) -> dict:
    from tripartite_memory.core import MemoryCore

    memory = MemoryCore(default_collection=collection)

    print(f"[bench] Ingesting {len(ENTRIES)} corpus documents...")
    await ingest_corpus(memory, collection, verbose)

    hits_at_1 = 0
    hits_at_k = 0
    misses = []

    print(f"[bench] Running {len(QA_PAIRS)} QA pairs (top_k={top_k})...")
    for i, pair in enumerate(QA_PAIRS):
        ctx = await memory.recall(
            intent=pair.question,
            collection=collection,
        )
        docs = [h.content for h in (ctx.historical_precedents or [])][:top_k]

        combined_at_1 = docs[0] if docs else ""
        combined_at_k = " ".join(docs)

        frag = pair.ground_truth_fragment.lower()
        at_1 = frag in combined_at_1.lower()
        at_k = frag in combined_at_k.lower()

        if at_1:
            hits_at_1 += 1
        if at_k:
            hits_at_k += 1
        else:
            misses.append({
                "question": pair.question,
                "expected_fragment": pair.ground_truth_fragment,
            })

        if verbose:
            status = "HIT@1" if at_1 else ("HIT@K" if at_k else "MISS")
            print(f"  [{status:5s}] {pair.question[:72]}")
            if not at_k:
                print(f"          expected: {pair.ground_truth_fragment!r}")

    n = len(QA_PAIRS)
    result = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "n": n,
        "top_k": top_k,
        "collection": collection,
        "recall_at_1": round(hits_at_1 / n, 3),
        "recall_at_k": round(hits_at_k / n, 3),
        "hits_at_1": hits_at_1,
        "hits_at_k": hits_at_k,
        "misses": misses,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="tripartite-memory retrieval benchmark")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--collection", default=BENCH_COLLECTION)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true", help="Output raw JSON only")
    args = parser.parse_args()

    result = asyncio.run(run_async(args.top_k, args.collection, args.verbose and not args.json))

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"\n{'='*50}")
    print(f"  Recall@1 : {result['recall_at_1']:.1%}  ({result['hits_at_1']}/{result['n']})")
    print(f"  Recall@{args.top_k} : {result['recall_at_k']:.1%}  ({result['hits_at_k']}/{result['n']})")
    if result["misses"]:
        print(f"\n  Misses ({len(result['misses'])}):")
        for m in result["misses"]:
            print(f"    - {m['question'][:72]}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
