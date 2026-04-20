from neo4j import AsyncGraphDatabase
from typing import List, Dict, Any, Optional
from ..types import GraphNode

class RelationalEngine:
    """Neo4j adapter for the Capability Graph (Dependencies)."""
    def __init__(self, uri: str, user: str, password: str):
        self.driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def close(self):
        await self.driver.close()

    async def get_blast_radius(self, intent_keyword: str, depth: int = 2, authorized_ring: int = 3) -> List[GraphNode]:
        """Find nodes and relationships within a specific depth, respecting Ring visibility."""
        # We filter by ensuring the node has a Ring label >= authorized_ring
        # Or no ring label (defaults to 3)
        query = """
        MATCH (m:Mandate)
        WHERE toLower(m.title) CONTAINS toLower($kw)
        OPTIONAL MATCH path = (m)-[*1..%d]-(related)
        UNWIND nodes(path) as n
        WITH n, path
        WHERE any(label IN labels(n) WHERE label STARTS WITH 'Ring' AND toInteger(substring(label, 4)) >= $auth_ring)
           OR NOT any(label IN labels(n) WHERE label STARTS WITH 'Ring')
        RETURN DISTINCT elementId(n) as id, labels(n) as labels, properties(n) as props, length(path) as depth
        LIMIT 20
        """ % depth

        async with self.driver.session() as session:
            result = await session.run(query, kw=intent_keyword[:50], auth_ring=authorized_ring)
            nodes = []
            async for record in result:
                # Extract ring level from labels if present
                ring = 3
                for lbl in record["labels"]:
                    if lbl.startswith("Ring"):
                        ring = int(lbl[4:])

                nodes.append(GraphNode(
                    id=str(record["id"]),
                    label=record["labels"][0] if record["labels"] else "Unknown",
                    properties=record["props"],
                    depth=record["depth"] or 0,
                    ring_level=ring
                ))
            return nodes

    async def ingest_intent(self, title: str, actor: str, tags: Optional[List[str]] = None, ring_level: int = 3):
        """Merge a new intent/mandate node into the graph with a Ring label."""
        ring_label = f"Ring{ring_level}"
        query = f"""
        MERGE (m:Mandate {{title: $title}})
        SET m.created_at = datetime(), m.actor = $actor, m.status = 'PENDING'
        WITH m
        CALL apoc.create.addLabels(m, [$ring_label]) YIELD node
        FOREACH (tag IN $tags |
            MERGE (t:Tag {{name: tag}})
            MERGE (m)-[:TAGGED_WITH]->(t)
        )
        """
        async with self.driver.session() as session:
            await session.run(query, title=title, actor=actor, tags=tags or [], ring_label=ring_label)
