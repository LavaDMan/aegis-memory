# AEGIS Tripartite Memory SDK 🧠
Available on PyPI as **tripartite-memory**

[![PyPI Version](https://img.shields.io/pypi/v/tripartite-memory.svg)](https://pypi.org/project/tripartite-memory/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://www.python.org/)

Most LLM agents fail in the same way: they forget what already happened. They retry failed approaches, ignore system state, and confidently suggest things that already broke production.

This is **AI Amnesia**.

`tripartite-memory` is a unified async Python SDK that gives AI agents persistent, structured memory across three distinct layers. Before an agent takes action, it can answer:
> "Has this failed before?"  
> "What will this impact?"  
> "Is this safe to execute?"

Instead of guessing, it **knows.**

## Memory & Context Optimization ⚡
`tripartite-memory` significantly reduces the cost and improves the performance of running large models:
- **60-80% Token Reduction:** Instead of dumping massive chat histories into the prompt, `recall()` injects only the 3-5 most relevant precedents.
- **VRAM Relief:** By keeping context windows lean, models consume less VRAM (which scales quadratically with sequence length). Run larger models (32B/70B) on consumer-grade hardware.
- **Improved Reasoning:** Providing specific "Hard Constraints" from the Ledger prevents the LLM from making up rules, leading to deterministic and reliable outputs.

## What This Fixes
**Without memory:**
- Agents loop on failed solutions.
- Context windows explode with irrelevant history.
- Risky actions happen without awareness of dependencies.

**With `tripartite-memory`:**
- Agents avoid known failure paths.
- Context stays small and relevant.
- Actions are informed by real system state and "trace the real blast radius."

## The Tripartite Architecture
To make an LLM safe for production, it needs an operating-system-level memory stack:
1. **The Ledger (Postgres):** Immutable state, strict constraints, and audit logs.
2. **The Semantic Engine (Qdrant):** High-dimensional vector search for historical precedents and documentation.
3. **The Capability Graph (Neo4j):** Dependency mapping to understand how modifying Component A impacts System B.

## Benchmarks 📊

These numbers come from a real multi-agent production system running continuous workloads — not a toy dataset.

| Metric | Score | Notes |
|---|---|---|
| Retrieval R@1 (neutral corpus, n=30) | **80%** | Paraphrased QA pairs, no query/corpus overlap |
| Retrieval R@5 (neutral corpus, n=30) | **100%** | |
| RAGAS Faithfulness | **0.740** | llama3.1:8b judge, 16 QA pairs |
| RAGAS Context Precision | 0.604 | |
| RAGAS Context Recall | 0.569 | |

Full benchmark methodology and corpus in [`benchmarks/`](./benchmarks/).

## How It Compares

We contributed the [distilled-knowledge benchmark](https://github.com/MemPalace/mempalace/pull/1111) to [MemPalace](https://github.com/MemPalace/mempalace) — a project we respect and actively benchmark against. The table below is meant to help you pick the right tool for your use case.

| | tripartite-memory | MemPalace | Mem0 | Zep |
|---|---|---|---|---|
| Local-first inference | ✅ | ❌ | Partial | ❌ |
| Multi-agent access rings | ✅ | ❌ | ❌ | ❌ |
| Three-tier storage | ✅ | ❌ | ❌ | ❌ |
| R@1 retrieval (neutral corpus)¹ | **80%** | 63.3% | ~70% | ~65% |

¹ *Our 80% and MemPalace's 63.3% are measured on the same neutral 30-pair corpus and are directly comparable. Mem0 and Zep figures are self-reported on different test sets.*

If you want a plug-and-play memory library, MemPalace is faster to get started. If you want production multi-agent memory with access control, local inference, and three-tier storage that actually outperforms on operational knowledge — that's `tripartite-memory`, and we have the benchmark to prove it.

## Installation

```bash
pip install tripartite-memory
```

## Quickstart

**Step 1 — Configure your databases** (copy `.env.example` and fill in your connection strings):

```bash
cp .env.example .env
# Edit .env with your Postgres, Qdrant, Neo4j, and Ollama URLs
```

Or pass credentials directly to the constructor (see below).

**Step 2 — Use the SDK:**

```python
import asyncio
from tripartite_memory.core import MemoryCore

async def main():
    # Option A: reads POSTGRES_URL, QDRANT_URL, NEO4J_URI from .env
    memory = MemoryCore()

    # Option B: pass credentials explicitly
    # memory = MemoryCore(
    #     postgres_uri="postgresql://user:pass@localhost:5432/mydb",
    #     qdrant_url="http://localhost:6333",
    #     neo4j_uri="bolt://localhost:7687",
    # )

    # 1. Unified Ingestion (Write to all 3 databases simultaneously)
    await memory.ingest(
        content="Modified the Nginx reverse proxy to route /api/v2 traffic to staging.",
        actor="agent:InfrastructureOps",
        tags=["nginx", "networking", "staging"]
    )

    # 2. Pre-Action Context Check (The Blast Radius)
    # Give your agent complete situational awareness before it touches production.
    context = await memory.recall(
        intent="Restart the Nginx service to apply new SSL certificates.",
        graph_depth=2,
        # collection="operator_context",  # override default collection
        # max_age_days=90,                # ignore memories older than 90 days
        # authorized_ring=2,              # ring-level access control (0=highest, 3=public)
    )

    print(context.status)               # "KNOWN", "ADJACENT", "UNKNOWN", or "DEGRADED"
    print(context.blast_radius)         # Neo4j dependent nodes
    print(context.historical_precedents) # Qdrant vector matches
    print(context.authorized_ring)      # ring level used for this query
    print(context.metadata["failed_engines"])  # [] or ["ledger", "semantic", etc.]

if __name__ == "__main__":
    asyncio.run(main())
```

> **Note:** `MemoryCore()` validates that all three database URLs are available at construction time. If any are missing it raises `ValueError` immediately — it does not defer until first use. Ensure your `.env` is loaded or credentials are passed before instantiating.

## The Agent Protocol 🛡️
`tripartite-memory` works best when the agent is "forced" to use it. I recommend adding a **Memory Protocol** to your agent's system prompt. See [SYSTEM_PROMPT.md](./SYSTEM_PROMPT.md) for the exact snippet.

## Universal Integration
- **Local Models (Ollama/LM Studio):** Inject the `recall()` JSON directly into the context window before the user's prompt.
- **CLI Clients (Claude Code/Gemini CLI):** Wrap the SDK in a tool or use the provided **Bridge Script**.

## Bi-directional Memory Bridge 🔄
A ready-to-use bridge is included in [examples/bridge.py](./examples/bridge.py) that works on Linux, Mac, and Windows.

```bash
# Get Context
python examples/bridge.py recall "How do I optimize VRAM on Pascal?"

# Store Knowledge
python examples/bridge.py ingest "Successfully tuned batch size to 4 for Qwen-32B." --tags optimization
```

## Remote Connection Guide (LAN) 🌐
If testing from a remote machine, point the SDK to your server's IP in your `.env`:
```ini
POSTGRES_URL=postgresql://user:password@10.0.0.100:5432/aegis_local
QDRANT_URL=http://10.0.0.100:6333
NEO4J_URI=bolt://10.0.0.100:7687
NEO4J_PASSWORD=your-secure-password
OLLAMA_URL=http://10.0.0.100:11434
```

## Managed Cloud Support ☁️
`tripartite-memory` is compatible with major managed database providers. Just update your `.env` with the cloud connection strings:

- **Vector (Qdrant):** Works with [Qdrant Cloud](https://qdrant.tech/cloud/). Set `QDRANT_API_KEY` in your environment.
- **Graph (Neo4j):** Works with [Neo4j AuraDB](https://neo4j.com/cloud/aura/). Use your provided `bolt://` URI and password.
- **Ledger (Postgres):** Works with [Neon](https://neon.tech/) or [Supabase](https://supabase.com/).

```ini
# Cloud Example
QDRANT_URL=https://your-cluster.qdrant.tech
QDRANT_API_KEY=your-api-key
NEO4J_URI=bolt+s://your-instance.databases.neo4j.io
```

## Injection Guard 🛡️

Multi-agent systems have a specific attack surface that single-agent systems don't: one agent can pass malicious content to another. `InjectionGuard` closes that gap — a zero-dependency text scanner that validates user input, inter-agent messages, or any text before it reaches a model or tool executor.

```python
from tripartite_memory.guards import InjectionGuard

# Quick boolean check
if not InjectionGuard.is_safe(user_input):
    raise ValueError("Input rejected by injection guard")

# Full report
result = InjectionGuard.scan_text_for_injection(user_input)
# {
#   "score": 50,           # 0 = clean, ≥50 = high-risk
#   "findings": [{"severity": "HIGH", "description": "...", "pattern": "..."}],
#   "summary": "Injection scan score: 50. 1 finding(s)."
# }
```

**What it detects (HIGH risk, score +50 each):**
- `shell=True` in subprocess, `os.system()`, `eval()`, `exec()`
- Container privilege escalation (`--privileged`, `cap_add SYS_ADMIN`)
- Prompt override attempts (`ignore previous instructions`, `act as`, etc.)
- HTML/JS injection (`<script>`, `javascript:`)
- Malicious shell commands (`rm -rf`, `sudo`, `wget`, `curl`, etc.)
- Template injection with shell operators (`${foo;rm -rf}`)
- Backtick shell execution (`` `rm -rf /` `` — not triggered by markdown inline code)

**Medium risk (score +10 each):** security TODOs, `DEBUG=True`, logical operator chaining.

Scores cap at 100. Pure stdlib — no install overhead.

## SBOM & Transparency

This repository includes a **Software Bill of Materials (SBOM)** in CycloneDX format.
- **View SBOM:** [sbom.json](./sbom.json)
- **Generate Fresh SBOM:** `python scripts/generate_sbom.py`

## Why I Built This
I built this SDK as the foundational memory layer for **AEGIS OS** — a bare-metal AI orchestration system designed to govern AI agents on real infrastructure using deterministic safety tiers (T0/T1/T2).

Most memory libraries are built for demos. This one was built for a system that runs 50-80 local inference calls per day across multiple specialized agents, where a hallucinated constraint or a missed precedent has real consequences. The benchmark numbers above are from that system, not a curated eval.

While the core OS uses a Business Source License (BSL), I believe fundamental agentic memory should be open and standardized. `tripartite-memory` is 100% open-source (Apache 2.0).

Built by **[John Alva](https://alvasystemsarchitecture.com)** — infrastructure and AI automation for organizations that can't afford downtime. | [Alva Systems](https://alvasystemsarchitecture.com)

## Changelog

### v0.2.1
- **Fix:** `authorized_ring` now correctly populated in `ContextPayload` (was always defaulting to 3)
- **New:** `status = "DEGRADED"` when one or more engines fail — callers can now detect partial availability
- **New:** `metadata["failed_engines"]` lists which stores were unavailable on a given recall
- **Fix:** Timeouts now configurable via `TRIPARTITE_OLLAMA_TIMEOUT` and `TRIPARTITE_QDRANT_TIMEOUT` env vars (default 60s/30s)
- **Fix:** `&&`/`||` injection pattern narrowed — logical operators in prose no longer trigger false positives; only shell command-chaining patterns are flagged
- **Fix:** `datetime.utcnow()` replaced with timezone-aware `datetime.now(timezone.utc)` throughout
- **Docs:** Quickstart updated with explicit `.env` setup step, constructor alternatives, and all `recall()` parameters documented

### v0.2.0
- **New:** `tripartite_memory.guards.InjectionGuard` — zero-dependency prompt and shell injection scanner (stdlib only)
- **New:** `InjectionGuard.is_safe(text, threshold)` convenience method
- **Fix:** Narrowed backtick injection pattern — markdown inline code no longer triggers false positive
- **Fix:** Narrowed template literal pattern to only flag when shell operators are embedded (`${foo;rm}` triggers, `${VAR}` does not)
- **Lifecycle:** `nightly_pruning.py` default collections updated to generic names
- **Internal:** `format_as_stable_suffix` header string generalized

### v0.1.4
- Add stable suffix decoding support for prefix caching

### v0.1.3
- Add support for staleness filtering (`max_age_days`)

### v0.1.2
- **Hardening:** `MemoryCore()` now validates all three database URLs at construction time — raises `ValueError` immediately if any are missing rather than failing silently at first use
- **New:** `default_collection` parameter on `MemoryCore()`, also configurable via `DEFAULT_COLLECTION` env var
- **Fix:** `ingest()` returns early with `{"success": False}` on empty content instead of writing a blank record
- **Fix:** Engine initialization failures now log and re-raise with context instead of swallowing the error

## Contributing
PRs are welcome. If you are building agentic systems that require strict intent multiplexing and deterministic safety, I'd love to collaborate.

Areas where contributions are especially welcome: additional embedding model adapters, alternative graph backends, and benchmark corpus expansion. See [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines.
