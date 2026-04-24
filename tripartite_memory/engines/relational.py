import re
from neo4j import AsyncGraphDatabase
from typing import List, Dict, Any, Optional
from ..types import GraphNode

# Patterns to extract as tags from ingested content
_IDENT_RE = re.compile(
    r'(?<![a-zA-Z])'           # not preceded by a letter
    r'('
    r'Ph\d{2,4}'               # Ph250, Ph364
    r'|[a-z][a-z0-9]*(?:_[a-z0-9_]+)+'  # snake_case identifiers
    r'|_[a-z][a-z0-9_]+'       # _leading_underscore names
    r'|[A-Z][A-Z0-9_]{3,}'     # ALL_CAPS_CONSTANTS
    r'|\.[a-z]{2,10}\b'        # dotfiles like .venv
    r')'
)

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "when",
    "what", "which", "where", "have", "been", "will", "are", "was", "not",
}

# Known AEGIS service names for service-mention tags
_KNOWN_SERVICES = {
    "mcp_hub", "idle_advisory", "idle_job_runner", "sentinel_classifier",
    "agent_gateway", "ollama_coordinator", "ingestion_worker", "probe_runner",
    "remediation_bridge", "trust_engine", "mandate_pipeline", "dashboard_v2",
}


def _extract_tags(text: str) -> list[str]:
    """Extract technical identifiers from content text to use as graph tags."""
    tags = set()
    for m in _IDENT_RE.finditer(text):
        tok = m.group(1).strip("_").lower()
        if len(tok) >= 4 and tok not in _STOPWORDS:
            tags.add(tok)
    # Also catch known service names even without underscores
    text_lower = text.lower()
    for svc in _KNOWN_SERVICES:
        if svc in text_lower:
            tags.add(svc)
    return list(tags)[:30]  # cap to avoid huge tag sets


def _tech_tokens_from_intent(intent: str) -> list[str]:
    """
    Extract ONLY technical identifiers from a query intent for tag matching.
    Deliberately narrow: plain English words must not leak into this list or
    they will match too many Tag nodes and flood the conflict resolver.
    Matches: snake_case, Ph-numbers, dotfiles, ALL_CAPS constants.
    """
    return _extract_tags(intent)  # already limited to technical patterns + known services


class RelationalEngine:
    """Neo4j adapter for the Capability Graph (Dependencies)."""
    def __init__(self, uri: str, user: str, password: str):
        self.driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def close(self):
        await self.driver.close()

    async def get_blast_radius(self, intent_keyword: str, depth: int = 2, authorized_ring: int = 3) -> List[GraphNode]:
        """Find nodes and relationships within a specific depth, respecting Ring visibility."""
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
                ring = 3
                for lbl in record["labels"]:
                    if lbl.startswith("Ring"):
                        try:
                            ring = int(lbl[4:])
                        except ValueError:
                            pass
                nodes.append(GraphNode(
                    id=str(record["id"]),
                    label=record["labels"][0] if record["labels"] else "Unknown",
                    properties=record["props"],
                    depth=record["depth"] or 0,
                    ring_level=ring
                ))
            return nodes

    async def ingest_intent(self, title: str, actor: str, tags: Optional[List[str]] = None, ring_level: int = 3):
        """
        Merge a Mandate node into the graph.
        Auto-extracts technical identifiers from title as additional Tag nodes.
        Ring level stored as property (APOC-free) + label when APOC available.
        """
        explicit_tags = list(tags or [])
        auto_tags = _extract_tags(title)
        all_tags = list(set(explicit_tags + auto_tags))

        # Merge Mandate + tags without requiring APOC
        query = """
        MERGE (m:Mandate {title: $title})
        SET m.created_at = coalesce(m.created_at, datetime()),
            m.actor = $actor,
            m.status = 'PENDING',
            m.ring_level = $ring_level
        WITH m
        FOREACH (tag IN $tags |
            MERGE (t:Tag {name: tag})
            MERGE (m)-[:TAGGED_WITH]->(t)
        )
        """
        async with self.driver.session() as session:
            await session.run(
                query,
                title=title,
                actor=actor,
                tags=all_tags,
                ring_level=ring_level,
            )

    async def add_service_node(self, service_name: str, node_id: str, ring_level: int = 3):
        """
        Ph367-A: Merge a Service node and link it to any Mandate nodes
        that mention this service name as a tag.
        """
        query = """
        MERGE (s:Service {name: $name})
        SET s.node_id = $node_id, s.ring_level = $ring_level,
            s.last_seen = datetime()
        WITH s
        MATCH (t:Tag {name: $name})
        MERGE (s)-[:MATCHES_TAG]->(t)
        """
        async with self.driver.session() as session:
            try:
                await session.run(query, name=service_name, node_id=node_id, ring_level=ring_level)
            except Exception:
                pass

    async def get_tag_matched_titles(self, intent: str, authorized_ring: int = 3) -> list[str]:
        """
        Ph391 — Find Mandate titles whose Tag nodes match technical identifiers
        extracted from the query intent.  Returns up to 10 titles for Qdrant
        prefix lookup.  Relies on tag_name_idx + mandate_title_idx being ONLINE.
        """
        tokens = _tech_tokens_from_intent(intent)
        if not tokens:
            return []
        query = """
        MATCH (t:Tag)
        WHERE any(kw IN $tokens WHERE t.name CONTAINS kw)
        MATCH (m:Mandate)-[:TAGGED_WITH]->(t)
        WHERE NOT any(label IN labels(m)
                      WHERE label STARTS WITH 'Ring'
                        AND toInteger(substring(label, 4)) < $auth_ring)
        RETURN DISTINCT m.title as title
        LIMIT 10
        """
        async with self.driver.session() as session:
            try:
                result = await session.run(query, tokens=tokens, auth_ring=authorized_ring)
                return [r["title"] async for r in result]
            except Exception:
                return []

    async def add_kernel_event(self, service_name: str, event_id: str,
                               event_type: str, ts_ms: int,
                               extra: Optional[Dict[str, Any]] = None):
        """
        Ph367-A: Merge a KernelEvent node and link it to its Service.
        Adds :CRASHED label when exit_code != 0.
        """
        exit_code = (extra or {}).get("exit_code", 0)
        crashed = event_type == "process_exit" and exit_code not in (0, -1, None)
        labels = "KernelEvent" + (":CRASHED" if crashed else "")
        query = f"""
        MERGE (e:{labels} {{event_id: $event_id}})
        SET e.type = $event_type, e.ts_ms = $ts_ms,
            e.exit_code = $exit_code, e.extra = $extra_json
        WITH e
        MATCH (s:Service {{name: $svc}})
        MERGE (s)-[:HAD_KERNEL_EVENT]->(e)
        """
        import json
        async with self.driver.session() as session:
            try:
                await session.run(
                    query,
                    event_id=event_id,
                    event_type=event_type,
                    ts_ms=ts_ms,
                    exit_code=exit_code,
                    extra_json=json.dumps(extra or {}),
                    svc=service_name,
                )
            except Exception:
                pass
