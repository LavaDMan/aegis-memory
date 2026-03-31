from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class MemoryHit(BaseModel):
    """A single semantic match from the Vector store."""
    score: float
    payload: Dict[str, Any]
    source: str = "qdrant"

class GraphNode(BaseModel):
    """A node or relationship from the Capability Graph."""
    id: str
    label: str
    properties: Dict[str, Any]
    depth: int

class LedgerState(BaseModel):
    """Immutable state record from the Ledger."""
    id: str
    title: str
    description: Optional[str]
    status: str
    priority: int

class ContextPayload(BaseModel):
    """The unified tripartite context object returned to the agent."""
    intent: str
    status: str = Field(..., description="KNOWN, ADJACENT, or UNKNOWN based on memory density")
    confidence_score: float = 0.0
    built_at: datetime = Field(default_factory=datetime.utcnow)
    
    historical_precedents: List[MemoryHit] = []
    blast_radius: List[GraphNode] = []
    hard_constraints: List[LedgerState] = []
    knowledge_gaps: List[str] = []
    
    metadata: Dict[str, Any] = {}
