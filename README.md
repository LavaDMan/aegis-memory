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

## Installation

```bash
pip install tripartite-memory
```

## Quickstart
Initialize the `MemoryCore` with your database credentials (or use a `.env` file).

```python
import asyncio
from tripartite_memory.core import MemoryCore

async def main():
    # Automatically loads from .env
    memory = MemoryCore()

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
        graph_depth=2
    )

    print(context.status) # "KNOWN", "ADJACENT", or "UNKNOWN"
    print(context.blast_radius) # Neo4j dependent nodes
    print(context.historical_precedents) # Qdrant vector matches

if __name__ == "__main__":
    asyncio.run(main())
```

## The Agent Protocol 🛡️
`tripartite-memory` works best when the agent is "forced" to use it. We recommend adding a **Memory Protocol** to your agent's system prompt. See [SYSTEM_PROMPT.md](./SYSTEM_PROMPT.md) for the exact snippet.

## Universal Integration
- **Local Models (Ollama/LM Studio):** Inject the `recall()` JSON directly into the context window before the user's prompt.
- **CLI Clients (Claude Code/Gemini CLI):** Wrap the SDK in a tool or use the provided **Bridge Script**.

## Bi-directional Memory Bridge 🔄
We provide a ready-to-use bridge in [examples/bridge.py](./examples/bridge.py) that works on Linux, Mac, and Windows.

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

## SBOM & Transparency 🛡️
In alignment with AEGIS OS security standards, this repository includes a **Software Bill of Materials (SBOM)** in CycloneDX format. 
- **View SBOM:** [sbom.json](./sbom.json)
- **Generate Fresh SBOM:** `python scripts/generate_sbom.py`

## Why We Built This
We built this SDK as the foundational memory layer for **AEGIS OS** — a bare-metal AI orchestration system designed to govern AI agents on real infrastructure using deterministic safety tiers (T0/T1/T2).

While the core OS uses a Business Source License (BSL), we believe fundamental agentic memory should be open and standardized. `tripartite-memory` is 100% open-source (Apache 2.0).

Built by [Alva Systems](https://alvasystemsarchitecture.com) — infrastructure and AI automation for organizations that can't afford downtime.

## Contributing
PRs are welcome. If you are building agentic systems that require strict intent multiplexing and deterministic safety, we'd love to collaborate.
