"""
Ph1916: Deterministic conflict resolution layer for tripartite memory.

Priority (highest → lowest):
  1. ledger  — authoritative current state (Postgres project_mandates)
  2. graph   — structural/dependency facts (Neo4j)
  3. semantic — historical/probabilistic (Qdrant)

Rules
-----
* When a semantic recall conflicts with a ledger constraint on the same
  entity, the ledger value wins.
* When graph structural facts conflict with semantic precedents, graph wins.
* Semantic entries older than RECENCY_THRESHOLD_DAYS have their
  `recency_penalty_applied` flag set in the ResolutionDecision, signalling
  that their score has already been penalised by MemoryCore._apply_recency_decay.
* Resolution decisions are surfaced in ContextPayload.metadata so agents can
  see which store won and why.

This module is a thin post-processor — it does NOT restructure the recall
path, call any store directly, or modify scores a second time.
"""

import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from .types import GraphNode, LedgerState, MemoryHit

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Entries older than this (days) are flagged as recency-penalised in decisions.
# Scores are decayed upstream by MemoryCore._apply_recency_decay (30-day half-life);
# we only record the flag here — no double-penalty.
RECENCY_THRESHOLD_DAYS: int = 30

# Regex that matches phase codes: Ph1916, Ph161.1, ph200, Ph1919_local …
_PHASE_RE = re.compile(r"\b[Pp]h\d{1,4}(?:[._]\d+)?\b")

# Canonical status normalisations (longest match wins — sort order matters)
_STATUS_SYNONYMS: List[Tuple[str, str]] = [
    ("in_progress", "IN_PROGRESS"),
    ("in progress", "IN_PROGRESS"),
    ("completed",   "COMPLETED"),
    ("resolved",    "COMPLETED"),
    ("fixed",       "COMPLETED"),
    ("closed",      "COMPLETED"),
    ("deprecated",  "DEPRECATED"),
    ("archived",    "DEPRECATED"),
    ("pending",     "PENDING"),
    ("approved",    "APPROVED"),
    ("active",      "IN_PROGRESS"),
    ("running",     "IN_PROGRESS"),
    ("done",        "COMPLETED"),
]


# ---------------------------------------------------------------------------
# Public data type
# ---------------------------------------------------------------------------

@dataclass
class ResolutionDecision:
    """
    Records which store won a conflict and why.
    Serialised into ContextPayload.metadata["resolution_decisions"] so any
    consuming agent can inspect the resolution without reasoning about it.
    """
    entity: str                     # e.g. "Ph1916", "Ph161"
    field: str                      # e.g. "status", "description"
    winner: str                     # "ledger" | "graph" | "semantic" | "no_conflict"
    winning_value: Any              # the authoritative value chosen
    store_values: Dict[str, Any]    # {store_name: observed_value} — transparency
    reason: str                     # human-readable explanation
    recency_penalty_applied: bool = False  # True when semantic entry was old

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_phases(text: str) -> List[str]:
    """
    Return normalised phase codes from *text*.
    e.g. "Ph1916", "Ph161", "Ph200" — uppercased prefix, numeric suffix kept.
    """
    return [
        "Ph" + m.group()[2:]  # strip the matched Pp+h and reattach canonical "Ph"
        for m in _PHASE_RE.finditer(text)
    ]


def _normalise_status(text: str) -> Optional[str]:
    """
    Scan *text* for the longest matching status synonym and return the
    canonical form (e.g. "COMPLETED").  Returns None if nothing matches.
    """
    lower = text.lower()
    for term, canonical in _STATUS_SYNONYMS:
        if term in lower:
            return canonical
    return None


def _age_days(payload: Dict[str, Any]) -> Optional[float]:
    """
    Return age in days for a semantic payload, or None if timestamps are
    missing / unparseable.  Uses `captured_at` falling back to
    `last_validated_at`.
    """
    ts_str = payload.get("captured_at") or payload.get("last_validated_at")
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(str(ts_str))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max((now - ts).total_seconds() / 86400, 0.0)
    except (ValueError, TypeError):
        return None


def _is_old(payload: Dict[str, Any]) -> bool:
    """True if the semantic entry exceeds RECENCY_THRESHOLD_DAYS."""
    age = _age_days(payload)
    return age is not None and age > RECENCY_THRESHOLD_DAYS


# ---------------------------------------------------------------------------
# Core resolver
# ---------------------------------------------------------------------------

class ConflictResolver:
    """
    Deterministic priority resolver for tripartite recall results.

    Usage (inside MemoryCore.recall after all three engines have returned)::

        resolver = ConflictResolver()
        decisions, gaps = resolver.resolve(ledger_res, graph_res, active_semantic)

    Returns
    -------
    decisions : list[ResolutionDecision]
        One entry per detected conflict.  Add to
        ``ContextPayload.metadata["resolution_decisions"]``.
    gaps : list[str]
        Human-readable conflict/stale lines.  Extend into
        ``ContextPayload.knowledge_gaps``.
    """

    def resolve(
        self,
        ledger: List[LedgerState],
        graph: List[GraphNode],
        semantic: List[MemoryHit],
    ) -> Tuple[List[ResolutionDecision], List[str]]:
        """Main entry point — O(n²) but bounded by store result limits."""
        decisions: List[ResolutionDecision] = []
        gaps: List[str] = []

        # --- Rule 1: ledger > semantic -----------------------------------
        penalised = self._mark_aged_semantic(semantic)
        decisions.extend(
            self._ledger_vs_semantic(ledger, semantic, penalised, gaps)
        )

        # --- Rule 2: graph > semantic ------------------------------------
        decisions.extend(
            self._graph_vs_semantic(graph, semantic, penalised, gaps)
        )

        # --- Rule 3: stale / aging notices (no ledger/graph to contradict) ---
        self._stale_notices(semantic, penalised, decisions, gaps)

        return decisions, gaps

    # ------------------------------------------------------------------
    # Private methods
    # ------------------------------------------------------------------

    def _mark_aged_semantic(self, semantic: List[MemoryHit]) -> Set[int]:
        """
        Return object IDs of semantic hits older than RECENCY_THRESHOLD_DAYS.
        Scores are NOT modified here — MemoryCore already applied decay.
        """
        return {id(hit) for hit in semantic if _is_old(hit.payload)}

    def _ledger_vs_semantic(
        self,
        ledger: List[LedgerState],
        semantic: List[MemoryHit],
        penalised: Set[int],
        gaps: List[str],
    ) -> List[ResolutionDecision]:
        """
        Rule 1: ledger status is authoritative.
        Detects when a semantic entry claims a different status for the same
        phase/mandate that the ledger currently tracks.
        """
        decisions: List[ResolutionDecision] = []
        if not ledger or not semantic:
            return decisions

        # Phase → LedgerState fast lookup
        ledger_by_phase: Dict[str, LedgerState] = {}
        for mandate in ledger:
            search_text = f"{mandate.title} {mandate.description or ''}"
            for ph in _extract_phases(search_text):
                ledger_by_phase[ph] = mandate
            # Also index by the mandate title itself (lowercased) for word-overlap checks

        # Also build a title-word index for fuzzy entity matching
        ledger_title_words: Dict[str, LedgerState] = {
            m.title.lower(): m for m in ledger
        }

        for hit in semantic[:10]:
            text = hit.payload.get("text", "")
            hit_phases = _extract_phases(text)
            hit_status = _normalise_status(text)
            aged = id(hit) in penalised

            for ph in hit_phases:
                if ph not in ledger_by_phase:
                    continue
                mandate = ledger_by_phase[ph]
                if hit_status is None:
                    continue
                if hit_status == mandate.status:
                    continue  # no conflict

                decision = ResolutionDecision(
                    entity=ph,
                    field="status",
                    winner="ledger",
                    winning_value=mandate.status,
                    store_values={
                        "ledger": mandate.status,
                        "semantic": hit_status,
                    },
                    reason=(
                        f"Ledger shows {ph} as {mandate.status}; "
                        f"semantic entry claims {hit_status}. "
                        f"Ledger is authoritative for current state."
                        + (" (semantic entry is aged >30d)" if aged else "")
                    ),
                    recency_penalty_applied=aged,
                )
                decisions.append(decision)
                gaps.append(
                    f"CONFLICT: {ph} status — ledger={mandate.status}, "
                    f"semantic={hit_status}. Ledger wins (authoritative)."
                )

        return decisions

    def _graph_vs_semantic(
        self,
        graph: List[GraphNode],
        semantic: List[MemoryHit],
        penalised: Set[int],
        gaps: List[str],
    ) -> List[ResolutionDecision]:
        """
        Rule 2: graph status/structural facts trump semantic precedents.
        Checks Neo4j node `status` property against semantic status claims
        for matching phase entities.
        """
        decisions: List[ResolutionDecision] = []
        if not graph or not semantic:
            return decisions

        # Phase → GraphNode fast lookup (only nodes with a `status` property)
        graph_by_phase: Dict[str, GraphNode] = {}
        for node in graph:
            props = node.properties or {}
            title = str(props.get("title", node.label))
            desc = str(props.get("description", ""))
            for ph in _extract_phases(f"{title} {desc}"):
                if props.get("status"):
                    graph_by_phase[ph] = node

        for hit in semantic[:10]:
            text = hit.payload.get("text", "")
            hit_phases = _extract_phases(text)
            hit_status = _normalise_status(text)
            aged = id(hit) in penalised

            for ph in hit_phases:
                if ph not in graph_by_phase:
                    continue
                node = graph_by_phase[ph]
                graph_status = node.properties.get("status", "").upper()
                if not graph_status or hit_status is None:
                    continue
                if hit_status == graph_status:
                    continue  # no conflict

                decision = ResolutionDecision(
                    entity=ph,
                    field="status",
                    winner="graph",
                    winning_value=graph_status,
                    store_values={
                        "graph": graph_status,
                        "semantic": hit_status,
                    },
                    reason=(
                        f"Graph shows {ph} status={graph_status}; "
                        f"semantic entry claims {hit_status}. "
                        f"Graph wins as structural authority."
                        + (" (semantic entry is aged >30d)" if aged else "")
                    ),
                    recency_penalty_applied=aged,
                )
                decisions.append(decision)
                gaps.append(
                    f"CONFLICT: {ph} status — graph={graph_status}, "
                    f"semantic={hit_status}. Graph wins (structural authority)."
                )

        return decisions

    def _stale_notices(
        self,
        semantic: List[MemoryHit],
        penalised: Set[int],
        decisions: List[ResolutionDecision],
        gaps: List[str],
    ) -> None:
        """
        Emit STALE / AGING notices for old semantic entries that haven't
        already been called out by a ledger or graph conflict decision.
        """
        conflicted_ids = {id(d) for d in decisions}  # already surfaced entries

        for hit in semantic[:10]:
            age = _age_days(hit.payload)
            if age is None:
                continue

            if age > 90 and id(hit) not in conflicted_ids:
                gaps.append(
                    f"STALE: Semantic entry ({age:.0f} days old, never revalidated) — "
                    f"treat with low confidence."
                )
            elif age > 60 and id(hit) not in conflicted_ids:
                gaps.append(
                    f"AGING: Semantic entry ({age:.0f} days since last validation) — "
                    f"consider verifying before acting on it."
                )
