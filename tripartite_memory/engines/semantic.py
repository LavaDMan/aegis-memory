import asyncio
import httpx
import os
import re
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from ..types import MemoryHit

# Stopwords excluded from keyword extraction
_STOPWORDS = frozenset({
    'a','an','the','is','are','was','were','be','been','being','have','has',
    'had','do','does','did','will','would','shall','should','may','might',
    'must','can','could','for','of','to','in','on','at','by','with','from',
    'into','through','this','that','these','those','it','its','how','what',
    'why','when','where','which','who','whom','and','or','but','not','no',
    'if','then','so','as','up','out','we','you','i','they','my','your','our',
    'get','set','use','used','using','make','made','need','also','just',
    'about','after','before','than','more','some','all','any','each',
})

_OLLAMA_TIMEOUT = float(os.getenv("TRIPARTITE_OLLAMA_TIMEOUT", "60"))
_QDRANT_TIMEOUT = float(os.getenv("TRIPARTITE_QDRANT_TIMEOUT", "30"))

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
                timeout=_OLLAMA_TIMEOUT,
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
                timeout=_QDRANT_TIMEOUT
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
                timeout=_QDRANT_TIMEOUT
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
                timeout=_QDRANT_TIMEOUT / 2,
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
                timeout=_QDRANT_TIMEOUT / 2,
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
                    timeout=_QDRANT_TIMEOUT,
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

    # ------------------------------------------------------------------ Ph328
    # Hybrid retrieval: keyword scan + semantic merge

    @staticmethod
    def _tokenize(text: str) -> frozenset:
        """Split text into a set of lowercase alphanumeric word tokens.
        Treats underscores, dots, arrows, etc. as separators so 'timeout_8b'
        yields {'timeout', '8b'} and 'switch' does NOT match 'switched'.
        """
        return frozenset(re.findall(r"[a-z0-9]+", text.lower()))

    @staticmethod
    def _query_terms(query: str) -> List[str]:
        """Return non-stopword word tokens from a query, ≥2 chars."""
        tokens = re.findall(r"[a-z0-9]+", query.lower())
        return [t for t in tokens if t not in _STOPWORDS and len(t) >= 2]

    @staticmethod
    def _semantic_weight(query: str, default: float = 0.55) -> float:
        """Tune semantic vs keyword weight by query character.

        Queries with technical identifiers (digit+letter combos like '8b',
        'ph330', or ALL-CAPS tokens ≥2 chars) lean more on keyword matching
        because semantic embeddings of short technical constants are unreliable.
        All other queries use the default weight.
        """
        # digit+letter combo: 8b, 32b, t2, ph333 …
        if re.search(r"\b[a-z]*\d+[a-z]+\b|\b[a-z]+\d+\b", query.lower()):
            return 0.45
        # ALL-CAPS token (acronym / constant): GPU, TIMEOUT, VRAM …
        if re.search(r"\b[A-Z]{2,}\b", query):
            return 0.45
        return default

    async def keyword_search(
        self,
        query: str,
        collection: str,
        limit: int = 10,
        authorized_ring: int = 3,
    ) -> List[MemoryHit]:
        """Full-collection keyword scan using word-token matching.

        Scores each point by the fraction of query terms whose exact word
        token appears in the document token set.  'switch' will NOT match
        'switched'; 'timeout' WILL match 'timeout_8b' (splits on '_').
        """
        terms = self._query_terms(query)
        if not terms:
            return []

        points = await self.scroll_collection(collection)

        hits: List[MemoryHit] = []
        for pt in points:
            payload = pt.get("payload", {})
            if payload.get("superseded"):
                continue
            if payload.get("ring_level", 3) < authorized_ring:
                continue
            text = payload.get("text", "")
            if not text:
                continue

            doc_tokens = self._tokenize(text)
            matched = sum(1 for t in terms if t in doc_tokens)
            if matched == 0:
                continue

            hits.append(MemoryHit(
                score=matched / len(terms),
                payload=payload,
                source=collection,
                ring_level=payload.get("ring_level", 3),
            ))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    async def hybrid_search(
        self,
        query: str,
        collection: str,
        limit: int = 10,
        since: Optional[datetime] = None,
        authorized_ring: int = 3,
    ) -> List[MemoryHit]:
        """Parallel semantic + keyword retrieval merged by weighted score.

        Weight auto-tunes per query: technical queries (digit+letter combos,
        ALL-CAPS tokens) shift weight toward keyword (0.45 sem / 0.55 kw)
        because semantic embeddings of short constants are unreliable.
        Default: 0.55 sem / 0.45 kw — favours semantic but gives keyword
        enough influence to surface entries missing from semantic top-N.
        """
        sem_w = self._semantic_weight(query)
        kw_w = 1.0 - sem_w

        semantic_hits, keyword_hits = await asyncio.gather(
            self.search(query, collection, limit=limit * 2, since=since,
                        authorized_ring=authorized_ring),
            self.keyword_search(query, collection, limit=limit * 2,
                                authorized_ring=authorized_ring),
        )

        # Merge: deduplicate by text, combine scores from both legs
        merged: Dict[str, Dict] = {}
        for h in semantic_hits:
            key = h.payload.get("text", "")
            if key:
                merged[key] = {"sem": h.score, "kw": 0.0, "hit": h}
        for h in keyword_hits:
            key = h.payload.get("text", "")
            if not key:
                continue
            if key in merged:
                merged[key]["kw"] = h.score
            else:
                merged[key] = {"sem": 0.0, "kw": h.score, "hit": h}

        results: List[MemoryHit] = []
        for v in merged.values():
            hit = v["hit"]
            hit.score = sem_w * v["sem"] + kw_w * v["kw"]
            results.append(hit)

        results.sort(key=lambda h: h.score, reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------ /Ph328

    # ------------------------------------------------------------------ Ph391
    # Tag-graph additive retrieval: fetch Qdrant points by Neo4j-matched titles

    async def fetch_by_title_prefixes(
        self,
        titles: List[str],
        collection: str,
        authorized_ring: int = 3,
    ) -> List[MemoryHit]:
        """
        Ph391 — Return Qdrant points whose text[:100] matches any of the given
        Mandate titles (stored in Neo4j as content[:100]).  Called after
        get_tag_matched_titles() so graph tag matches surface in recall results.
        """
        if not titles:
            return []
        title_set = {t[:100] for t in titles}
        points = await self.scroll_collection(collection)
        hits: List[MemoryHit] = []
        for pt in points:
            payload = pt.get("payload", {})
            if payload.get("superseded"):
                continue
            if payload.get("ring_level", 3) < authorized_ring:
                continue
            text = payload.get("text", "")
            if text[:100] in title_set:
                hits.append(MemoryHit(
                    score=0.30,
                    payload=payload,
                    source=collection,
                    ring_level=payload.get("ring_level", 3),
                ))
        return hits

    # ------------------------------------------------------------------ /Ph391

    async def close(self):
        pass
