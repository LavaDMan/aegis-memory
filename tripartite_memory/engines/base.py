class BaseEngine:
    """Base class for Tripartite engine adapters."""
    def __init__(self, uri: str):
        self.uri = uri

class LedgerEngine(BaseEngine):
    """Postgres implementation for State/Audit logging."""
    async def get_recent_state(self, limit: int = 5):
        return []

class SemanticEngine(BaseEngine):
    """Qdrant implementation for Vector memory."""
    async def search_similar(self, text: str, top_k: int = 3):
        return []

class RelationalEngine(BaseEngine):
    """Neo4j implementation for Graph/Dependency memory."""
    async def get_blast_radius(self, node_id: str, depth: int = 2):
        return []
