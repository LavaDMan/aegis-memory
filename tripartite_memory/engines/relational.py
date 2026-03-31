from neo4j import AsyncGraphDatabase
from typing import List, Dict, Any, Optional
from ..types import GraphNode

class RelationalEngine:
    """Neo4j adapter for the Capability Graph (Dependencies)."""
    def __init__(self, uri: str, user: str, password: str):
        self.driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def close(self):
        await self.driver.close()

    async def get_blast_radius(self, intent_keyword: str, depth: int = 2) -> List[GraphNode]:
        """Find nodes and relationships within a specific depth of the intent."""
        query = """
        MATCH (m:Mandate)
        WHERE toLower(m.title) CONTAINS toLower($kw)
        OPTIONAL MATCH path = (m)-[*1..%d]-(related)
        UNWIND nodes(path) as n
        RETURN DISTINCT elementId(n) as id, labels(n)[0] as label, properties(n) as props, length(path) as depth
        LIMIT 20
        """ % depth

        async with self.driver.session() as session:
            result = await session.run(query, kw=intent_keyword[:50])
            nodes = []
            async for record in result:
                nodes.append(GraphNode(
                    id=str(record["id"]),
                    label=record["label"],
                    properties=record["props"],
                    depth=record["depth"] or 0
                ))
            return nodes

    async def ingest_intent(self, title: str, actor: str, tags: Optional[List[str]] = None):
        """Merge a new intent/mandate node into the graph."""
        query = """
        MERGE (m:Mandate {title: $title})
        ON CREATE SET m.created_at = datetime(), m.actor = $actor, m.status = 'PENDING'
        WITH m
        FOREACH (tag IN $tags |
            MERGE (t:Tag {name: tag})
            MERGE (m)-[:TAGGED_WITH]->(t)
        )
        """
        async with self.driver.session() as session:
            await session.run(query, title=title, actor=actor, tags=tags or [])
