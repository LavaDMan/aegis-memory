# Contributing to tripartite-memory

PRs are welcome. Here's how to get oriented quickly.

## Areas where contributions are especially welcome

- **Embedding model adapters** — nomic-embed-text is the tested default; adapters for other Ollama models or OpenAI embeddings would be valuable
- **Graph backends** — Neo4j is the current implementation; a NetworkX or Memgraph adapter would help users without a Neo4j instance
- **Benchmark corpus expansion** — additional QA pairs or domain-specific corpora in `benchmarks/corpus.py`
- **Cloud provider guides** — connection examples for Supabase, PlanetScale, Pinecone, etc.

## Setup

```bash
git clone https://github.com/LavaDMan/aegis-memory.git
cd aegis-memory
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill in your local DB URLs
```

## Running tests

```bash
pytest tests/
```

## Running benchmarks

```bash
python benchmarks/retrieval_bench.py --verbose
```

## Guidelines

- Keep functions atomic and single-responsibility
- New engines must implement the same async interface as `LedgerEngine`, `SemanticEngine`, and `RelationalEngine`
- Any change to `recall()` or `ingest()` should include a benchmark run showing no regression against the baseline in `benchmarks/README.md`
- Open an issue before starting large refactors

## Reporting issues

Open a GitHub issue with: Python version, which database backends you're using, and the full traceback.
