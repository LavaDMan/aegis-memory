"""
Ph1916: Unit tests for tripartite_memory.resolution.ConflictResolver.

All tests are pure Python — no live Postgres/Qdrant/Neo4j required.
Run with:
    cd tripartite-memory-internal && python -m pytest tests/test_resolution.py -v
or standalone:
    python tripartite-memory-internal/tests/test_resolution.py
"""

import sys
import os
from datetime import datetime, timezone, timedelta

# Allow running as a script without install
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tripartite_memory.resolution import ConflictResolver, ResolutionDecision, RECENCY_THRESHOLD_DAYS
from tripartite_memory.types import LedgerState, GraphNode, MemoryHit

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _ledger(ph: str, status: str) -> LedgerState:
    return LedgerState(
        id=f"id-{ph}",
        title=f"{ph} Some mandate title",
        description=f"Description for {ph}",
        status=status,
        priority=5,
        ring_level=3,
    )


def _graph_node(ph: str, status: str) -> GraphNode:
    return GraphNode(
        id=f"neo4j:{ph}",
        label="Mandate",
        properties={"title": f"{ph} graph node", "status": status},
        depth=1,
        ring_level=3,
    )


def _semantic_hit(text: str, age_days: int = 5, score: float = 0.9) -> MemoryHit:
    captured = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
    return MemoryHit(
        score=score,
        payload={"text": text, "captured_at": captured},
        source="qdrant",
        ring_level=3,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_conflict_empty_inputs():
    """Resolver returns empty lists when no results are passed."""
    resolver = ConflictResolver()
    decisions, gaps = resolver.resolve([], [], [])
    assert decisions == []
    assert gaps == []


def test_ledger_wins_over_semantic_status_conflict():
    """
    Ledger shows Ph1916 as PENDING.
    Semantic entry says it's completed.
    → ledger wins.
    """
    ledger = [_ledger("Ph1916", "PENDING")]
    semantic = [_semantic_hit("Ph1916 mandate has been completed successfully", age_days=2)]

    resolver = ConflictResolver()
    decisions, gaps = resolver.resolve(ledger, [], semantic)

    assert len(decisions) == 1
    d = decisions[0]
    assert d.entity == "Ph1916"
    assert d.winner == "ledger"
    assert d.winning_value == "PENDING"
    assert d.store_values["semantic"] == "COMPLETED"
    assert "Ledger wins" in gaps[0]


def test_ledger_no_conflict_when_status_agrees():
    """No conflict when ledger and semantic agree on status."""
    ledger = [_ledger("Ph200", "IN_PROGRESS")]
    semantic = [_semantic_hit("Ph200 is in progress and running well", age_days=2)]

    resolver = ConflictResolver()
    decisions, gaps = resolver.resolve(ledger, [], semantic)

    conflict_decisions = [d for d in decisions if d.winner != "no_conflict"]
    conflict_gaps = [g for g in gaps if "CONFLICT" in g]
    assert conflict_decisions == []
    assert conflict_gaps == []


def test_graph_wins_over_semantic_status_conflict():
    """
    Graph shows Ph161 as APPROVED.
    Semantic entry says it's closed/completed.
    → graph wins.
    """
    graph = [_graph_node("Ph161", "APPROVED")]
    semantic = [_semantic_hit("Ph161 is done and closed", age_days=3)]

    resolver = ConflictResolver()
    decisions, gaps = resolver.resolve([], graph, semantic)

    assert len(decisions) == 1
    d = decisions[0]
    assert d.entity == "Ph161"
    assert d.winner == "graph"
    assert d.winning_value == "APPROVED"
    assert d.store_values["semantic"] == "COMPLETED"
    assert "Graph wins" in gaps[0]


def test_ledger_priority_over_graph_both_vs_semantic():
    """
    Both ledger and graph have Ph202, both conflict with semantic.
    Both should be detected as separate decisions.
    """
    ledger = [_ledger("Ph202", "PENDING")]
    graph = [_graph_node("Ph202", "PENDING")]
    semantic = [_semantic_hit("Ph202 was completed and resolved last week", age_days=3)]

    resolver = ConflictResolver()
    decisions, gaps = resolver.resolve(ledger, graph, semantic)

    winners = {d.winner for d in decisions}
    assert "ledger" in winners
    # graph may also fire since the same semantic hit conflicts with graph too
    assert len(decisions) >= 1


def test_recency_penalty_flagged_for_aged_semantic():
    """
    Semantic entry older than RECENCY_THRESHOLD_DAYS gets
    recency_penalty_applied=True in the decision.
    """
    ledger = [_ledger("Ph150", "PENDING")]
    aged_days = RECENCY_THRESHOLD_DAYS + 10
    semantic = [_semantic_hit("Ph150 completed milestone", age_days=aged_days)]

    resolver = ConflictResolver()
    decisions, gaps = resolver.resolve(ledger, [], semantic)

    assert len(decisions) == 1
    assert decisions[0].recency_penalty_applied is True
    assert "aged >30d" in decisions[0].reason


def test_no_recency_flag_for_fresh_semantic():
    """Fresh entries (< RECENCY_THRESHOLD_DAYS old) should NOT be flagged."""
    ledger = [_ledger("Ph151", "PENDING")]
    semantic = [_semantic_hit("Ph151 completed milestone", age_days=5)]

    resolver = ConflictResolver()
    decisions, gaps = resolver.resolve(ledger, [], semantic)

    if decisions:
        assert decisions[0].recency_penalty_applied is False


def test_stale_notice_emitted_for_90day_entry():
    """
    Semantic entries > 90 days old with no conflict should emit STALE notice.
    """
    # No ledger/graph so no CONFLICT decision, just a stale notice
    semantic = [_semantic_hit("some unrelated text about networking", age_days=95)]

    resolver = ConflictResolver()
    decisions, gaps = resolver.resolve([], [], semantic)

    stale_gaps = [g for g in gaps if g.startswith("STALE")]
    assert len(stale_gaps) >= 1
    assert "95" in stale_gaps[0] or "days" in stale_gaps[0]


def test_aging_notice_for_60_to_90_day_entry():
    """Entries 60–90 days old should emit AGING (not STALE) notice."""
    semantic = [_semantic_hit("some text about caching strategies", age_days=70)]

    resolver = ConflictResolver()
    decisions, gaps = resolver.resolve([], [], semantic)

    aging_gaps = [g for g in gaps if g.startswith("AGING")]
    assert len(aging_gaps) >= 1


def test_resolution_decision_serialises_to_dict():
    """ResolutionDecision.as_dict() must be JSON-serialisable (no custom types)."""
    import json

    ledger = [_ledger("Ph999", "PENDING")]
    semantic = [_semantic_hit("Ph999 was fixed and completed", age_days=2)]

    resolver = ConflictResolver()
    decisions, _ = resolver.resolve(ledger, [], semantic)
    assert len(decisions) == 1

    d_dict = decisions[0].as_dict()
    # Must not raise
    serialised = json.dumps(d_dict)
    parsed = json.loads(serialised)

    assert parsed["entity"] == "Ph999"
    assert parsed["winner"] == "ledger"
    assert "store_values" in parsed
    assert "reason" in parsed


def test_no_phase_in_semantic_text_yields_no_conflict():
    """If semantic text has no phase codes, resolver produces no conflict decisions."""
    ledger = [_ledger("Ph1916", "PENDING")]
    semantic = [_semantic_hit("The network latency was improved last sprint", age_days=2)]

    resolver = ConflictResolver()
    decisions, gaps = resolver.resolve(ledger, [], semantic)

    conflict_decisions = [d for d in decisions if d.winner in ("ledger", "graph")]
    assert conflict_decisions == []


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_no_conflict_empty_inputs,
        test_ledger_wins_over_semantic_status_conflict,
        test_ledger_no_conflict_when_status_agrees,
        test_graph_wins_over_semantic_status_conflict,
        test_ledger_priority_over_graph_both_vs_semantic,
        test_recency_penalty_flagged_for_aged_semantic,
        test_no_recency_flag_for_fresh_semantic,
        test_stale_notice_emitted_for_90day_entry,
        test_aging_notice_for_60_to_90_day_entry,
        test_resolution_decision_serialises_to_dict,
        test_no_phase_in_semantic_text_yields_no_conflict,
    ]
    failed = []
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed.append(t.__name__)
        except Exception as e:
            print(f"  ERROR {t.__name__}: {e}")
            failed.append(t.__name__)

    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed")
    if failed:
        sys.exit(1)
