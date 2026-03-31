import asyncio
import os
import sys
from tripartite_memory.core import MemoryCore

async def test_sdk_recall():
    print("🚀 Initializing aegis-memory SDK...")
    
    # Use environment variables or defaults
    POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://langfuse:langfuse@localhost:5432/aegis_local")
    QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "neo4j")
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

    memory = MemoryCore(
        postgres_uri=POSTGRES_URL,
        qdrant_url=QDRANT_URL,
        neo4j_uri=NEO4J_URI,
        neo4j_auth=(NEO4J_USER, NEO4J_PASS),
        ollama_url=OLLAMA_URL
    )

    intent = "Research GPU optimization for Pascal P6000"
    print(f"🔍 Testing recall for intent: '{intent}'")
    
    try:
        context = await memory.recall(intent=intent, graph_depth=2)
        
        print(f"✅ Status: {context.status}")
        print(f"✅ Confidence: {context.confidence_score}")
        print(f"✅ Semantic Hits: {len(context.historical_precedents)}")
        print(f"✅ Graph Nodes: {len(context.blast_radius)}")
        print(f"✅ Ledger Mandates: {len(context.hard_constraints)}")
        
        # Verify structure
        assert context.intent == intent
        
    except Exception as e:
        print(f"❌ SDK Recall Failed: {e}")
        raise e
    finally:
        await memory.close()

if __name__ == "__main__":
    if sys.platform == 'win32':
        import selectors
        loop_factory = lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        asyncio.run(test_sdk_recall(), loop_factory=loop_factory)
    else:
        asyncio.run(test_sdk_recall())
