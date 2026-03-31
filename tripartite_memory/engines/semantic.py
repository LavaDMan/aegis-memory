import httpx
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from ..types import MemoryHit

class SemanticEngine:
    """Qdrant adapter for Tripartite Semantic Memory."""
    def __init__(self, url: str, embedding_url: str, model: str = "nomic-embed-text", api_key: Optional[str] = None):
        self.url = url
        self.embedding_url = embedding_url
        self.model = model
        self.api_key = api_key

    async def _embed(self, text: str) -> List[float]:
        """Generate vector via Ollama."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.embedding_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=60.0
            )
            resp.raise_for_status()
            return resp.json()["embedding"]

    def _get_headers(self) -> Dict[str, str]:
        headers = {}
        if self.api_key:
            headers["api-key"] = self.api_key
        return headers

    async def search(self, text: str, collection: str = "execution_memory", limit: int = 5) -> List[MemoryHit]:
        """Semantic search against Qdrant."""
        vector = await self._embed(text)
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.url}/collections/{collection}/points/search",
                json={
                    "vector": vector,
                    "limit": limit,
                    "with_payload": True
                },
                headers=self._get_headers(),
                timeout=30.0
            )
            resp.raise_for_status()
            results = resp.json().get("result", [])
            return [MemoryHit(
                score=r["score"],
                payload=r.get("payload", {}),
                source=collection
            ) for r in results]

    async def upsert(self, content: str, actor: str, tags: Optional[List[str]] = None, collection: str = "john_context") -> str:
        """Embed and upsert content to Qdrant."""
        vector = await self._embed(content)
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, content))
        
        async with httpx.AsyncClient() as client:
            # Note: Qdrant Cloud often prefers PUT for point upserts
            resp = await client.put(
                f"{self.url}/collections/{collection}/points",
                json={
                    "points": [{
                        "id": point_id,
                        "vector": vector,
                        "payload": {
                            "text": content,
                            "actor": actor,
                            "tags": tags or [],
                            "captured_at": datetime.utcnow().isoformat()
                        }
                    }]
                },
                headers=self._get_headers(),
                timeout=30.0
            )
            resp.raise_for_status()
            return point_id

    async def close(self):
        """Httpx client is used context-managed per request currently."""
        pass
