import psycopg
import psycopg.types.json
from typing import List, Dict, Any, Optional
from ..types import LedgerState

class LedgerEngine:
    """Postgres adapter for the Tripartite Ledger (State/Audit)."""
    def __init__(self, uri: str):
        self.uri = uri

    async def get_active_mandates(self, limit: int = 5) -> List[LedgerState]:
        """Fetch high-priority pending or in-progress mandates."""
        async with await psycopg.AsyncConnection.connect(self.uri) as conn:
            async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                await cur.execute("""
                    SELECT id, title, description, status, priority
                    FROM project_mandates
                    WHERE status IN ('IN_PROGRESS', 'APPROVED', 'PENDING')
                    ORDER BY 
                        CASE WHEN status = 'IN_PROGRESS' THEN 0 
                             WHEN status = 'APPROVED' THEN 1 
                             ELSE 2 END,
                        priority DESC
                    LIMIT %s
                """, (limit,))
                rows = await cur.fetchall()
                return [LedgerState(
                    id=str(r["id"]),
                    title=r["title"],
                    description=r["description"],
                    status=r["status"],
                    priority=r["priority"]
                ) for r in rows]

    async def log_transaction(self, content: str, actor: str, tags: Optional[List[str]] = None) -> str:
        """Log a new memory entry to the ledger."""
        async with await psycopg.AsyncConnection.connect(self.uri) as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO aegis_change_log (change_type, title, summary, details, affected_ai)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    "session_memory",
                    f"Memory: {content[:50]}...",
                    content[:200],
                    psycopg.types.json.Json({"actor": actor, "tags": tags or []}),
                    ['agent_os', 'mcp_hub']
                ))
                res = await cur.fetchone()
                await conn.commit()
                return str(res[0])

    async def close(self):
        """No persistent connection to close for current psycopg implementation."""
        pass
