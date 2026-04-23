# tripartite-memory Benchmarks

Reproducible benchmarks for the numbers published in the main README.

## Distilled Knowledge Retrieval Benchmark

**What it tests:** Recall@1 and Recall@5 on a 30-document corpus of engineering
constraints. QA pairs are paraphrased — query wording deliberately avoids the
exact vocabulary in the source document, testing semantic retrieval rather than
keyword matching.

**Reported baseline (v0.2.1, nomic-embed-text):**

| Metric | Score |
|---|---|
| Recall@1 | **80.0%** |
| Recall@5 | **100.0%** |

**Run it:**

```bash
# 1. Start Qdrant and Ollama with nomic-embed-text
docker run -p 6333:6333 qdrant/qdrant
ollama pull nomic-embed-text

# 2. Configure .env (copy from repo root)
cp ../.env.example ../.env

# 3. Run
pip install tripartite-memory
python benchmarks/retrieval_bench.py --verbose

# JSON output for scripting
python benchmarks/retrieval_bench.py --json
```

**Corpus:** [`corpus.py`](./corpus.py) — 30 prose documents, self-contained,
no external dependencies.

This benchmark was also contributed to [MemPalace](https://github.com/MemPalace/mempalace/pull/1111)
as the distilled-knowledge benchmark category. MemPalace scores 63.3% R@1 on
the same corpus using its default ChromaDB backend.

## RAGAS Faithfulness Benchmark

RAGAS measures four RAG dimensions: faithfulness, answer relevancy, context
precision, and context recall. Requires a running Ollama instance with a judge
model (default: `llama3.1:8b`).

**Reported baseline (v0.2.1):**

| Metric | Score |
|---|---|
| Faithfulness | **0.740** |
| Context Precision | 0.604 |
| Context Recall | 0.569 |
| Answer Relevancy | 0.468* |

*Answer relevancy is lower than retrieval quality suggests because questions
where context genuinely doesn't contain the answer score 0.0 relevancy — this
is correct behaviour, not a regression.*

RAGAS runner coming in a future release. The corpus and QA pairs in `corpus.py`
are compatible with any RAGAS-based evaluation pipeline.
