import asyncio
import os
import sys
import json
import argparse
import structlog

# Redirect all structlog output to stderr so stdout stays clean for JSON capture.
# MemoryCore configures structlog internally; this override must happen before import.
structlog.configure(
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO+
)

from tripartite_memory.core import MemoryCore

# Ph164: auto-compress oversized content before Qdrant ingest
_KERNEL_TOKEN_THRESHOLD = int(os.getenv("MAX_KERNEL_TOKENS", "500"))

def _maybe_compress(content: str) -> str:
    """Compress content if it exceeds the kernel token threshold."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        if len(enc.encode(content)) <= _KERNEL_TOKEN_THRESHOLD:
            return content
        # Lazy import to avoid hard dep when not needed
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services"))
        from agent_os.knowledge_kernel import compress_conversation_log
        kernel = compress_conversation_log({"messages": [content]}, strategy="recursive")
        print(
            json.dumps({"kernel_compression": kernel["scores"]}),
            file=sys.stderr,
        )
        return kernel["summary"]
    except Exception as e:
        print(f"⚠️  kernel compression skipped: {e}", file=sys.stderr)
        return content

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
        print(f"❌ INITIALIZATION FAILED: {e}", file=sys.stderr)
        print("Please ensure your .env file is correctly configured.", file=sys.stderr)
        sys.exit(1)

    try:
        if args.command == "recall":
            context = await memory.recall(intent=args.intent, collection=args.collection)
            print(context.model_dump_json(indent=2))
        
        elif args.command == "ingest":
            ingested_content = _maybe_compress(args.content)
            res = await memory.ingest(
                content=ingested_content,
                actor=args.actor,
                tags=args.tags,
                collection=args.collection
            )
            print(json.dumps(res, indent=2))
        
        else:
            parser.print_help()

    except Exception as e:
        print(f"❌ OPERATION FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        await memory.close()

if __name__ == "__main__":
    if loop_factory:
        asyncio.run(run_bridge(), loop_factory=loop_factory)
    else:
        asyncio.run(run_bridge())
