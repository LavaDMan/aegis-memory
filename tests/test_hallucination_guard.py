import asyncio
import os
import sys
from tripartite_memory.core import MemoryCore

async def test_sdk_hallucination_guard():
    print("🚀 Initializing aegis-memory SDK (Hallucination Guard Test)...")
    
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

    # Use an identifier that might fuzzy-match (like .7) but is strictly different (.70)
    intent = "What are the mandates for node .70 (Windows Desktop)?"
    print(f"🔍 Testing recall for intent: '{intent}'")
    
    try:
        context = await memory.recall(intent=intent, graph_depth=2)
        
        print(f"✅ Status: {context.status}")
        print(f"✅ Confidence Score: {context.confidence_score}")
        print(f"✅ Semantic Hits: {len(context.historical_precedents)}")
        
        if context.status == "UNKNOWN":
            print("🎉 SUCCESS: Hallucination Guard correctly identified low confidence/gap for specific node .70")
        else:
            print(f"⚠️  Hallucination Guard let it through as {context.status}. Adjusting thresholds may be needed.")

        if context.knowledge_gaps:
            print(f"✅ Knowledge Gaps identified: {context.knowledge_gaps}")

    except Exception as e:
        print(f"❌ SDK Test Failed: {e}")
        raise e
    finally:
        await memory.close()

if __name__ == "__main__":
    if sys.platform == 'win32':
        import selectors
        loop_factory = lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        asyncio.run(test_sdk_hallucination_guard(), loop_factory=loop_factory)
    else:
        asyncio.run(test_sdk_hallucination_guard())
