import asyncio
import structlog
import os
import re
from datetime import datetime, timedelta
from typing import Any, List, Dict, Optional
from dotenv import load_dotenv

from .types import ContextPayload, MemoryHit, GraphNode, LedgerState
from .engines.ledger import LedgerEngine
from .engines.semantic import SemanticEngine
from .engines.relational import RelationalEngine
from .resolution import ConflictResolver

log = structlog.get_logger()

class MemoryCore:
    """
    The Tripartite Memory Orchestrator.
    Fuses Ledger (State), Semantic (Vector), and Graph (Dependency) memory 
    into a single agentic context.
    """
    def __init__(
        self, 
        postgres_uri: Optional[str] = None, 
        qdrant_url: Optional[str] = None, 
        neo4j_uri: Optional[str] = None,
        neo4j_auth: Optional[tuple] = None,
        ollama_url: Optional[str] = None,
        embedding_model: str = "nomic-embed-text",
        default_collection: str = "memory"
    ):
        # Load environment variables from .env if present
        load_dotenv()
        
        self.postgres_uri = postgres_uri or os.getenv("POSTGRES_URL")
        self.qdrant_url = qdrant_url or os.getenv("QDRANT_URL")
        self.qdrant_api_key = os.getenv("QDRANT_API_KEY")
        self.neo4j_uri = neo4j_uri or os.getenv("NEO4J_URI")
        self.default_collection = os.getenv("DEFAULT_COLLECTION", default_collection)
        
        # Neo4j Auth construction
        if neo4j_auth:
            self.neo4j_user, self.neo4j_pass = neo4j_auth
        else:
            self.neo4j_user = os.getenv("NEO4J_USER", "neo4j")
            self.neo4j_pass = os.getenv("NEO4J_PASSWORD", "neo4j")

        self.ollama_url = ollama_url or os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.embedding_model = embedding_model
        
        self.log = log.bind(component="MemoryCore")

        # Initialize and validate engine adapters
        try:
            if not self.postgres_uri:
                raise ValueError("POSTGRES_URL is required but not provided.")
            if not self.qdrant_url:
                raise ValueError("QDRANT_URL is required but not provided.")
            if not self.neo4j_uri:
                raise ValueError("NEO4J_URI is required but not provided.")

            self.ledger = LedgerEngine(self.postgres_uri)
            self.semantic = SemanticEngine(self.qdrant_url, self.ollama_url, embedding_model, api_key=self.qdrant_api_key)
            self.graph = RelationalEngine(self.neo4j_uri, self.neo4j_user, self.neo4j_pass)
            self.log.info("engines_initialized")
        except Exception as e:
            self.log.error("engine_initialization_failed", error=str(e))
            raise

    async def ingest(self, content: str, actor: str, tags: Optional[List[str]] = None, collection: Optional[str] = None, ring_level: int = 3) -> Dict[str, Any]:
        """
        Unified write operation. Fans out the data to all three databases.
        Stamps data with a Context Ring (0-3).
        """
        if not content:
            return {"success": False, "error": "Content cannot be empty"}

        target_collection = collection or self.default_collection
        self.log.info("unified_ingest_started", actor=actor, content_len=len(content), collection=target_collection, ring=ring_level)
        
        # Parallel Ingestion
        ledger_task = self.ledger.log_transaction(content, actor, tags, ring_level=ring_level)
        semantic_task = self.semantic.upsert(content, actor, tags, collection=target_collection, ring_level=ring_level)
        graph_task = self.graph.ingest_intent(content[:100], actor, tags, ring_level=ring_level)
        
        results = await asyncio.gather(
            ledger_task, semantic_task, graph_task,
            return_exceptions=True
        )
        
        return {
            "ledger_id": results[0] if not isinstance(results[0], Exception) else None,
            "semantic_id": results[1] if not isinstance(results[1], Exception) else None,
            "graph_success": not isinstance(results[2], Exception),
            "errors": [str(r) for r in results if isinstance(r, Exception)]
        }

    async def recall(self, intent: str, graph_depth: int = 2, collection: Optional[str] = None, max_age_days: Optional[int] = None, authorized_ring: int = 3) -> ContextPayload:
        """
        The Pre-Action Context Check.
        Retrieves state, semantic similarity, and blast radius in a single pass.
        Strictly enforces Context Ring boundaries (agents cannot see lower rings).
        """
        if not intent:
            return ContextPayload(intent="", status="UNKNOWN", knowledge_gaps=["Empty intent provided"])

        target_collection = collection or self.default_collection
        self.log.info("tripartite_recall_started", intent=intent, collection=target_collection, ring=authorized_ring)
        
        # Determine cutoff date if specified
        since_date = None
        if max_age_days:
            since_date = datetime.utcnow() - timedelta(days=max_age_days)

        # Parallel Fan-out to all three storage engines with Ring enforcement
        ledger_task = self.ledger.get_active_mandates(limit=5, authorized_ring=authorized_ring)
        semantic_task = self.semantic.search(intent, collection=target_collection, limit=10, since=since_date, authorized_ring=authorized_ring)
        graph_task = self.graph.get_blast_radius(intent, depth=graph_depth, authorized_ring=authorized_ring)
        
        results = await asyncio.gather(
            ledger_task, semantic_task, graph_task,
            return_exceptions=True
        )
        
        # Check if all engines failed
        if all(isinstance(r, Exception) for r in results):
            error_msg = f"All tripartite engines failed: {results}"
            self.log.error("total_recall_failure", error=error_msg)
            raise RuntimeError(error_msg)

        ledger_res = results[0] if not isinstance(results[0], Exception) else []
        semantic_res = results[1] if not isinstance(results[1], Exception) else []
        graph_res = results[2] if not isinstance(results[2], Exception) else []
        
        if any(isinstance(r, Exception) for r in results):
            self.log.warning("partial_recall_failure", errors=[str(r) for r in results if isinstance(r, Exception)])

        # Hallucination Guard: Identify strict keywords (IPs, project codes)
        strict_keywords = self._extract_identifiers(intent)
        filtered_semantic = []
        gaps = []

        for hit in semantic_res:
            content = str(hit.payload.get("text", "")).lower()
            if all(kw.lower() in content for kw in strict_keywords):
                filtered_semantic.append(hit)
        
        if strict_keywords and not filtered_semantic:
            gaps.append(f"Strict identifiers {strict_keywords} requested but no exact matches found in semantic memory.")

        # Ph161.1 — Apply recency decay to semantic scores
        active_semantic = filtered_semantic if filtered_semantic else semantic_res
        active_semantic = self._apply_recency_decay(active_semantic)

        # Recalculate Confidence based on decay-adjusted results
        confidence = self._calculate_confidence(active_semantic, graph_res, has_keyword_match=bool(filtered_semantic))

        if strict_keywords and not filtered_semantic:
            confidence = confidence * 0.2
            status = "UNKNOWN"
        else:
            status = "KNOWN" if confidence > 0.8 else "ADJACENT" if confidence > 0.4 else "UNKNOWN"

        # Ph1916 — Deterministic conflict resolution: ledger > graph > semantic
        # ConflictResolver is a thin post-processor; it does not call any store
        # or modify scores (decay was already applied above).
        resolver = ConflictResolver()
        resolution_decisions, conflict_gaps = resolver.resolve(ledger_res, graph_res, active_semantic)
        gaps.extend(conflict_gaps)

        payload = ContextPayload(
            intent=intent,
            status=status,
            confidence_score=round(confidence, 2),
            historical_precedents=active_semantic[:5],
            blast_radius=graph_res,
            hard_constraints=ledger_res,
            knowledge_gaps=gaps,
            metadata={
                "resolution_decisions": [d.as_dict() for d in resolution_decisions],
                "resolution_store_priority": ["ledger", "graph", "semantic"],
            }
        )

        return payload

    def _extract_identifiers(self, text: str) -> List[str]:
        """Extracts IP addresses and specific node/project identifiers."""
        if not text:
            return []
        # Match IPv4 addresses
        ips = re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', text)
        # Match node identifiers like .70 or .5 (if not part of IP)
        nodes = re.findall(r'(?<!\d)\.\d{1,3}\b', text)
        return list(set(ips + nodes))

    # Ph1917 — Stepped decay thresholds (days → score multiplier).
    # Supersedes the Ph161.1 continuous half-life model.
    # Configurable via env; TRIPARTITE_DECAY_ENABLED=false disables entirely.
    _DECAY_STEPS = [
        (365, 0.2),
        (180, 0.5),
        (90,  0.8),
    ]

    def _apply_recency_decay(self, hits: List[MemoryHit]) -> List[MemoryHit]:
        """
        Apply stepped time-based decay to semantic scores.

        Uses last_validated_at when available, falls back to captured_at.
        Skips points marked superseded=True.
        Decay brackets (configurable via env):
          > TRIPARTITE_DECAY_THRESHOLD_DAYS_365 → 0.2x
          > TRIPARTITE_DECAY_THRESHOLD_DAYS_180 → 0.5x
          > TRIPARTITE_DECAY_THRESHOLD_DAYS_90  → 0.8x
          ≤ 90 days                              → 1.0x (no decay)
        Set TRIPARTITE_DECAY_ENABLED=false to bypass entirely.
        """
        if os.getenv("TRIPARTITE_DECAY_ENABLED", "true").lower() in ("false", "0"):
            return hits

        threshold_90  = int(os.getenv("TRIPARTITE_DECAY_THRESHOLD_DAYS_90",  "90"))
        threshold_180 = int(os.getenv("TRIPARTITE_DECAY_THRESHOLD_DAYS_180", "180"))
        threshold_365 = int(os.getenv("TRIPARTITE_DECAY_THRESHOLD_DAYS_365", "365"))
        steps = [(threshold_365, 0.2), (threshold_180, 0.5), (threshold_90, 0.8)]

        now = datetime.utcnow()
        for hit in hits:
            # Skip already-superseded entries — they should not influence recall ranking
            if hit.payload.get("superseded"):
                hit.score = 0.0
                continue

            ts_str = hit.payload.get("last_validated_at") or hit.payload.get("captured_at")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(str(ts_str))
                age_days = max((now - ts).total_seconds() / 86400, 0)
                multiplier = 1.0
                for threshold, factor in steps:
                    if age_days > threshold:
                        multiplier = factor
                        break
                hit.score = hit.score * multiplier
            except (ValueError, TypeError):
                pass  # malformed timestamp — leave raw score

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits

    async def mark_memory_superseded(
        self,
        point_id: str,
        collection: Optional[str] = None,
        reason: str = "",
    ) -> None:
        """
        Mark a semantic memory point as superseded (Ph1917 versioning).
        Called when a ledger update explicitly contradicts a stored semantic entry.
        Does NOT delete the point — preserves audit trail.
        """
        target = collection or self.default_collection
        self.log.info("mark_memory_superseded", point_id=point_id, collection=target, reason=reason)
        await self.semantic.mark_superseded(point_id, collection=target, reason=reason)

    def _calculate_confidence(self, hits: List[MemoryHit], nodes: List[GraphNode], has_keyword_match: bool = False) -> float:
        """Determine system certainty based on semantic similarity, recency, and graph density."""
        if not hits: return 0.0
        max_semantic = max((h.score for h in hits), default=0.0)
        graph_bonus = 0.15 if nodes else 0.0
        keyword_bonus = 0.2 if has_keyword_match else 0.0
        return min(max_semantic + graph_bonus + keyword_bonus, 1.0)
    
    def format_as_stable_suffix(self, payload: ContextPayload) -> str:
        """
        Formats the context payload into a stable string suitable for prefix caching.
        Ordering is deterministic to maximize cache hits in Ollama/llama.cpp.
        """
        lines = ["### SYSTEM CONTEXT (STABLE)"]
        
        # 1. Hard Constraints (Deterministic order by ID)
        if payload.hard_constraints:
            lines.append("\nRULES & CONSTRAINTS:")
            for m in sorted(payload.hard_constraints, key=lambda x: x.id):
                lines.append(f"- [{m.status}] {m.title}: {m.description}")

        # 2. Historical Precedents (Sorted by semantic score)
        if payload.historical_precedents:
            lines.append("\nRELEVANT HISTORY:")
            for h in sorted(payload.historical_precedents, key=lambda x: x.score, reverse=True):
                text = h.payload.get("text", "No content")
                lines.append(f"- {text}")

        # 3. Conflicts & Gaps (resolution warnings surface here)
        if payload.knowledge_gaps:
            # Separate conflicts from regular gaps
            conflict_lines = [g for g in payload.knowledge_gaps if g.startswith(("CONFLICT:", "STALE:", "AGING:"))]
            gap_lines = [g for g in payload.knowledge_gaps if g not in conflict_lines]
            if conflict_lines:
                lines.append("\nRESOLUTION WARNINGS (ledger > graph > semantic):")
                for c in conflict_lines:
                    lines.append(f"- {c}")
            if gap_lines:
                lines.append("\nIDENTIFIED GAPS:")
                for gap in sorted(gap_lines):
                    lines.append(f"- {gap}")

        return "\n".join(lines)

    async def close(self):
        """Cleanup resources across all engines."""
        await asyncio.gather(
            self.ledger.close(),
            self.semantic.close(),
            self.graph.close(),
            return_exceptions=True
        )
