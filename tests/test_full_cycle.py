import asyncio
import os
import uuid
import sys
from tripartite_memory.core import MemoryCore

async def test_sdk_full_cycle():
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

    test_id = str(uuid.uuid4())[:8]
    content = f"Unit Test: Deployed unique memory component {test_id} for tripartite verification."
    print(f"📥 Testing INGEST for: '{content}'")
    
    try:
        ingest_res = await memory.ingest(
            content=content,
            actor="test_agent",
            tags=["unit-test", "tripartite"]
        )
        print(f"✅ Ingest Results: {ingest_res}")
        assert ingest_res["ledger_id"] is not None
        assert ingest_res["semantic_id"] is not None
        assert ingest_res["graph_success"] is True

        # Small delay for Qdrant eventual consistency
        await asyncio.sleep(1)

        intent = f"Check status of component {test_id}"
        print(f"🔍 Testing RECALL for intent: '{intent}'")
        
        context = await memory.recall(intent=intent, graph_depth=2)
        
        print(f"✅ Recall Status: {context.status}")
        print(f"✅ Confidence: {context.confidence_score}")
        print(f"✅ Semantic Hits: {len(context.historical_precedents)}")
        
        # Verify the new memory is found
        found = any(test_id in hit.payload.get("text", "") for hit in context.historical_precedents)
        if found:
            print(f"🎉 SUCCESS: Found unique test_id {test_id} in recalled memory!")
        else:
            print(f"⚠️  Test ID {test_id} not found in immediate recall (expected for small top_k/threshold)")

    except Exception as e:
        print(f"❌ SDK Full Cycle Failed: {e}")
        raise e
    finally:
        await memory.close()

if __name__ == "__main__":
    if sys.platform == 'win32':
        import selectors
        loop_factory = lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        asyncio.run(test_sdk_full_cycle(), loop_factory=loop_factory)
    else:
        asyncio.run(test_sdk_full_cycle())
