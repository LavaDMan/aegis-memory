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
    parser = argparse.ArgumentParser(description="AEGIS Memory Bridge — Bi-directional Agent Memory")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Recall Command
    recall_parser = subparsers.add_parser("recall", help="Retrieve context for an intent")
    recall_parser.add_argument("intent", help="The semantic intent to search for")
    recall_parser.add_argument("--collection", default=None, help="Collection to search (defaults to env DEFAULT_COLLECTION)")
    recall_parser.add_argument("--suffix", action="store_true", help="Output as stable text suffix instead of JSON")

    # Ingest Command
    ingest_parser = subparsers.add_parser("ingest", help="Store new knowledge in the tripartite stack")
    ingest_parser.add_argument("content", help="The knowledge or action summary to store")
    ingest_parser.add_argument("--actor", default="remote_agent", help="The name of the agent/user")
    ingest_parser.add_argument("--tags", nargs="+", help="Tags for the memory entry")
    ingest_parser.add_argument("--collection", default=None, help="Collection to store in")

    args = parser.parse_args()

    # Initialize MemoryCore (handles env/dotenv loading and validation)
    try:
        memory = MemoryCore()
    except Exception as e:
        print(f"❌ INITIALIZATION FAILED: {e}")
        print("Please ensure your .env file is correctly configured.")
        sys.exit(1)

    try:
        if args.command == "recall":
            context = await memory.recall(intent=args.intent, collection=args.collection)
            print(context.model_dump_json(indent=2))
        
        elif args.command == "ingest":
            res = await memory.ingest(
                content=args.content,
                actor=args.actor,
                tags=args.tags,
                collection=args.collection
            )
            print(json.dumps(res, indent=2))
        
        else:
            parser.print_help()

    except Exception as e:
        print(f"❌ OPERATION FAILED: {e}")
        sys.exit(1)
    finally:
        await memory.close()

if __name__ == "__main__":
    if loop_factory:
        asyncio.run(run_bridge(), loop_factory=loop_factory)
    else:
        asyncio.run(run_bridge())
