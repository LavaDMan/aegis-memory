import asyncio
import os
import sys
import json
import argparse
import structlog
from tripartite_memory.core import MemoryCore

# Use the modernized loop factory for Windows compatibility
if sys.platform == 'win32':
    import selectors
    loop_factory = lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
else:
    loop_factory = None

async def run_bridge():
    # Check for required environment variables
    required_vars = ["POSTGRES_URL", "QDRANT_URL", "NEO4J_URI", "NEO4J_PASSWORD"]
    missing = [v for v in required_vars if not os.getenv(v)]
    
    if missing:
        print("❌ MISSING CONFIGURATION")
        print("Please set the following environment variables to connect to your AEGIS stack:")
        for v in missing:
            print(f"  - {v}")
        print("\nExample (PowerShell):")
        print('  $env:POSTGRES_URL="postgresql://user:pass@10.0.0.100:5432/aegis_local"')
        sys.exit(1)

    parser = argparse.ArgumentParser(description="AEGIS Memory Bridge — Bi-directional Agent Memory")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Recall Command
    recall_parser = subparsers.add_parser("recall", help="Retrieve context for an intent")
    recall_parser.add_argument("intent", help="The semantic intent to search for")
    recall_parser.add_argument("--collection", default="john_context", help="Qdrant collection to search")

    # Ingest Command
    ingest_parser = subparsers.add_parser("ingest", help="Store new knowledge in the tripartite stack")
    ingest_parser.add_argument("content", help="The knowledge or action summary to store")
    ingest_parser.add_argument("--actor", default="remote_agent", help="The name of the agent/user")
    ingest_parser.add_argument("--tags", nargs="+", help="Tags for the memory entry")

    args = parser.parse_args()

    # Initialize MemoryCore (now handles its own env/dotenv loading)
    memory = MemoryCore()

    try:
        # Verify required config after initialization
        if not memory.postgres_uri or not memory.qdrant_url:
            print("❌ MISSING CONFIGURATION")
            print("Please create a .env file or set environment variables.")
            print("See .env.example for required fields.")
            sys.exit(1)
        if args.command == "recall":
            context = await memory.recall(intent=args.intent, collection=args.collection)
            print(context.model_dump_json(indent=2))
        
        elif args.command == "ingest":
            res = await memory.ingest(
                content=args.content,
                actor=args.actor,
                tags=args.tags
            )
            print(json.dumps(res, indent=2))
        
        else:
            parser.print_help()

    finally:
        await memory.close()

if __name__ == "__main__":
    if loop_factory:
        asyncio.run(run_bridge(), loop_factory=loop_factory)
    else:
        asyncio.run(run_bridge())
