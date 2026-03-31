import asyncio
import os
from tripartite_memory.engines.semantic import SemanticEngine

async def test_cloud_header_injection():
    print("🚀 Testing Cloud Header Injection...")
    
    # Initialize engine with a dummy API key
    engine = SemanticEngine(
        url="http://localhost:6333",
        embedding_url="http://localhost:11434",
        api_key="sk-test-key-12345"
    )
    
    headers = engine._get_headers()
    print(f"📡 Generated Headers: {headers}")
    
    assert "api-key" in headers
    assert headers["api-key"] == "sk-test-key-12345"
    print("✅ SUCCESS: API Key correctly injected into headers.")

if __name__ == "__main__":
    asyncio.run(test_cloud_header_injection())
