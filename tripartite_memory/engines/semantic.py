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

    async def search(self, text: str, collection: str = "execution_memory", limit: int = 5, since: Optional[datetime] = None, authorized_ring: int = 3) -> List[MemoryHit]:
        """Semantic search with Context Ring payload filtering."""
        vector = await self._embed(text)
        
        query_payload = {
            "vector": vector,
            "limit": limit,
            "with_payload": True,
            "filter": {
                "must": [
                    {
                        "key": "ring_level",
                        "range": {
                            "gte": authorized_ring # Agents see their ring and higher (less sensitive) rings
                        }
                    }
                ]
            }
        }

        if since:
            query_payload["filter"]["must"].append({
                "key": "captured_at",
                "range": {"gt": since.isoformat()}
            })

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.url}/collections/{collection}/points/search",
                json=query_payload,
                headers=self._get_headers(),
                timeout=30.0
            )
            resp.raise_for_status()
            results = resp.json().get("result", [])
            return [MemoryHit(
                score=r["score"],
                payload=r.get("payload", {}),
                source=collection,
                ring_level=r.get("payload", {}).get("ring_level", 3)
            ) for r in results]

    async def upsert(self, content: str, actor: str, tags: Optional[List[str]] = None, collection: str = "operator_context", ring_level: int = 3) -> str:
        """Embed and upsert content with a Context Ring stamp."""
        vector = await self._embed(content)
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, content))

        async with httpx.AsyncClient() as client:
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
                            "captured_at": datetime.utcnow().isoformat(),
                            "last_validated_at": datetime.utcnow().isoformat(),
                            "ring_level": ring_level
                        }
                    }]
                },
                headers=self._get_headers(),
                timeout=30.0
            )
            resp.raise_for_status()
            return point_id

    async def touch_validated_at(self, point_id: str, collection: str = "operator_context") -> None:
        """Refresh last_validated_at on an existing point without re-embedding."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.url}/collections/{collection}/points/payload",
                json={
                    "payload": {"last_validated_at": datetime.utcnow().isoformat()},
                    "points": [point_id],
                },
                headers=self._get_headers(),
                timeout=15.0,
            )
            resp.raise_for_status()

    async def mark_superseded(self, point_id: str, collection: str = "operator_context", reason: str = "") -> None:
        """
        Mark a semantic point as superseded rather than deleting it.
        Preserves audit trail; superseded points are skipped by the conflict resolver.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.url}/collections/{collection}/points/payload",
                json={
                    "payload": {
                        "superseded": True,
                        "superseded_at": datetime.utcnow().isoformat(),
                        "superseded_reason": reason,
                    },
                    "points": [point_id],
                },
                headers=self._get_headers(),
                timeout=15.0,
            )
            resp.raise_for_status()

    async def scroll_collection(
        self,
        collection: str = "operator_context",
        batch_size: int = 256,
    ) -> List[Dict[str, Any]]:
        """
        Page through all points in a collection and return their payloads + ids.
        Used by the nightly pruning job.
        """
        points: List[Dict[str, Any]] = []
        offset = None

        async with httpx.AsyncClient() as client:
            while True:
                body: Dict[str, Any] = {
                    "limit": batch_size,
                    "with_payload": True,
                    "with_vector": False,
                }
                if offset is not None:
                    body["offset"] = offset

                resp = await client.post(
                    f"{self.url}/collections/{collection}/points/scroll",
                    json=body,
                    headers=self._get_headers(),
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json().get("result", {})
                batch = data.get("points", [])
                points.extend(batch)

                next_offset = data.get("next_page_offset")
                if not next_offset:
                    break
                offset = next_offset

        return points

    async def close(self):
        pass
