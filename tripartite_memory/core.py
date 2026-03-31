import asyncio
import structlog
import os
import re
from typing import Any, List, Dict, Optional
from dotenv import load_dotenv

from .types import ContextPayload, MemoryHit, GraphNode, LedgerState
from .engines.ledger import LedgerEngine
from .engines.semantic import SemanticEngine
from .engines.relational import RelationalEngine

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

    async def ingest(self, content: str, actor: str, tags: Optional[List[str]] = None, collection: Optional[str] = None) -> Dict[str, Any]:
        """
        Unified write operation. Fans out the data to all three databases.
        """
        if not content:
            return {"success": False, "error": "Content cannot be empty"}

        target_collection = collection or self.default_collection
        self.log.info("unified_ingest_started", actor=actor, content_len=len(content), collection=target_collection)
        
        # Parallel Ingestion
        ledger_task = self.ledger.log_transaction(content, actor, tags)
        semantic_task = self.semantic.upsert(content, actor, tags, collection=target_collection)
        graph_task = self.graph.ingest_intent(content[:100], actor, tags)
        
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

    async def recall(self, intent: str, graph_depth: int = 2, collection: Optional[str] = None, max_age_days: Optional[int] = None) -> ContextPayload:
        """
        The Pre-Action Context Check.
        Retrieves state, semantic similarity, and blast radius in a single pass.
        Includes a verification layer to prevent semantic hallucinations.
        """
        if not intent:
            return ContextPayload(intent="", status="UNKNOWN", knowledge_gaps=["Empty intent provided"])

        target_collection = collection or self.default_collection
        self.log.info("tripartite_recall_started", intent=intent, collection=target_collection, max_age_days=max_age_days)
        
        # Determine cutoff date if specified
        since_date = None
        if max_age_days:
            since_date = datetime.utcnow() - timedelta(days=max_age_days)

        # Parallel Fan-out to all three storage engines
        ledger_task = self.ledger.get_active_mandates(limit=5)
        semantic_task = self.semantic.search(intent, collection=target_collection, limit=10, since=since_date)
        graph_task = self.graph.get_blast_radius(intent, depth=graph_depth)
        
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

        # Recalculate Confidence based on filtered results
        confidence = self._calculate_confidence(filtered_semantic or semantic_res, graph_res, has_keyword_match=bool(filtered_semantic))
        
        if strict_keywords and not filtered_semantic:
            confidence = confidence * 0.2
            status = "UNKNOWN"
        else:
            status = "KNOWN" if confidence > 0.8 else "ADJACENT" if confidence > 0.4 else "UNKNOWN"

        payload = ContextPayload(
            intent=intent,
            status=status,
            confidence_score=round(confidence, 2),
            historical_precedents=filtered_semantic[:5] if filtered_semantic else semantic_res[:3],
            blast_radius=graph_res,
            hard_constraints=ledger_res,
            knowledge_gaps=gaps
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

    def _calculate_confidence(self, hits: List[MemoryHit], nodes: List[GraphNode], has_keyword_match: bool = False) -> float:
        """Determine system certainty based on semantic similarity and graph density."""
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
        lines = ["### AEGIS SYSTEM CONTEXT (STABLE)"]
        
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

        # 3. Knowledge Gaps
        if payload.knowledge_gaps:
            lines.append("\nIDENTIFIED GAPS:")
            for gap in sorted(payload.knowledge_gaps):
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
