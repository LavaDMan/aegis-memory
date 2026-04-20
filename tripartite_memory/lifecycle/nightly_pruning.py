"""
Ph1917: Nightly pruning job for the tripartite semantic (Qdrant) store.

Behaviour
---------
* Scrolls every collection listed in PRUNING_COLLECTIONS (comma-separated env var).
* Flags any point that meets BOTH criteria:
    - age (last_validated_at or captured_at) > PRUNING_MIN_AGE_DAYS (default 180)
    - stored score field < PRUNING_SCORE_THRESHOLD (default 0.5)
      OR no score field at all
* Does NOT delete. Posts a batched summary message to KNO-01 inbox via
  asyncpg (agent_messages table) so a human can confirm before any removal.
* Dry-run mode (PRUNING_DRY_RUN=true) prints candidates without writing.

Run as a standalone script:
    python -m tripartite_memory.lifecycle.nightly_pruning

Or import and call `run_pruning_job()` from a scheduler.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
import structlog
from dotenv import load_dotenv

load_dotenv()
log = structlog.get_logger("nightly_pruning")


# ---------------------------------------------------------------------------
# Config (all overridable via env)
# ---------------------------------------------------------------------------

def _env_int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


def _env_float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY: Optional[str] = os.getenv("QDRANT_API_KEY")

PRUNING_COLLECTIONS: List[str] = [
    c.strip()
    for c in os.getenv("PRUNING_COLLECTIONS", "execution_memory,operator_context,agent_context").split(",")
    if c.strip()
]
PRUNING_MIN_AGE_DAYS: int = _env_int("PRUNING_MIN_AGE_DAYS", 180)
PRUNING_SCORE_THRESHOLD: float = _env_float("PRUNING_SCORE_THRESHOLD", 0.5)
PRUNING_DRY_RUN: bool = os.getenv("PRUNING_DRY_RUN", "false").lower() in ("true", "1")
PRUNING_BATCH_SIZE: int = _env_int("PRUNING_BATCH_SIZE", 256)

POSTGRES_URL: Optional[str] = os.getenv("POSTGRES_URL")


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------

def _qdrant_headers() -> Dict[str, str]:
    if QDRANT_API_KEY:
        return {"api-key": QDRANT_API_KEY}
    return {}


async def _scroll_collection(client: httpx.AsyncClient, collection: str) -> List[Dict[str, Any]]:
    """Page through all points in a Qdrant collection."""
    points: List[Dict[str, Any]] = []
    offset = None

    while True:
        body: Dict[str, Any] = {
            "limit": PRUNING_BATCH_SIZE,
            "with_payload": True,
            "with_vector": False,
        }
        if offset is not None:
            body["offset"] = offset

        resp = await client.post(
            f"{QDRANT_URL}/collections/{collection}/points/scroll",
            json=body,
            headers=_qdrant_headers(),
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json().get("result", {})
        batch = data.get("points", [])
        points.extend(batch)

        next_offset = data.get("next_page_offset")
        if not next_offset:
            break
        offset = next_offset

    return points


def _age_days(payload: Dict[str, Any]) -> Optional[float]:
    """Return age in days using last_validated_at → captured_at fallback."""
    ts_str = payload.get("last_validated_at") or payload.get("captured_at")
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


def _is_pruning_candidate(point: Dict[str, Any]) -> bool:
    """True when a point meets both age and score criteria."""
    payload = point.get("payload") or {}

    # Skip already-superseded entries
    if payload.get("superseded"):
        return False

    age = _age_days(payload)
    if age is None or age <= PRUNING_MIN_AGE_DAYS:
        return False

    # Use stored `score` field if present; absent score = treat as below threshold
    score = payload.get("score")
    if score is None:
        return True  # no score recorded — flag it
    return float(score) < PRUNING_SCORE_THRESHOLD


# ---------------------------------------------------------------------------
# KNO-01 notification via asyncpg
# ---------------------------------------------------------------------------

async def _post_to_kno01(candidates: List[Dict[str, Any]]) -> None:
    """Insert a pruning review request into agent_messages for KNO-01."""
    if not POSTGRES_URL:
        log.warning("pruning_notify_skipped", reason="POSTGRES_URL not set")
        return

    try:
        import asyncpg  # type: ignore
    except ImportError:
        log.warning("pruning_notify_skipped", reason="asyncpg not installed")
        return

    summary_lines = []
    for item in candidates:
        col = item["collection"]
        pid = item["point_id"]
        age = item.get("age_days", "?")
        score = item.get("score", "n/a")
        preview = str(item.get("text_preview", ""))[:120]
        summary_lines.append(f"  [{col}] id={pid} age={age:.0f}d score={score}\n    \"{preview}\"")

    body = (
        f"NIGHTLY PRUNING REPORT — {datetime.utcnow().strftime('%Y-%m-%d')}\n"
        f"Candidates flagged for review: {len(candidates)}\n"
        f"Criteria: age > {PRUNING_MIN_AGE_DAYS}d AND score < {PRUNING_SCORE_THRESHOLD}\n\n"
        + "\n".join(summary_lines)
        + "\n\nAction: Review and call mark_superseded() or touch_validated_at() as appropriate."
    )

    conn = await asyncpg.connect(POSTGRES_URL)
    try:
        await conn.execute(
            """
            INSERT INTO agent_messages (from_agent, to_agent, subject, body, status, created_at)
            VALUES ($1, $2, $3, $4, 'UNREAD', NOW())
            """,
            "DEV-01",
            "KNO-01",
            f"[PRUNING] {len(candidates)} semantic points need review ({datetime.utcnow().strftime('%Y-%m-%d')})",
            body,
        )
        log.info("pruning_message_posted", to="KNO-01", candidate_count=len(candidates))
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Main job
# ---------------------------------------------------------------------------

async def run_pruning_job(dry_run: Optional[bool] = None) -> List[Dict[str, Any]]:
    """
    Scan all configured collections and flag stale low-confidence points.
    Returns the list of candidate dicts (useful for testing).
    """
    effective_dry_run = PRUNING_DRY_RUN if dry_run is None else dry_run
    candidates: List[Dict[str, Any]] = []

    log.info(
        "pruning_job_start",
        collections=PRUNING_COLLECTIONS,
        min_age_days=PRUNING_MIN_AGE_DAYS,
        score_threshold=PRUNING_SCORE_THRESHOLD,
        dry_run=effective_dry_run,
    )

    async with httpx.AsyncClient() as client:
        for collection in PRUNING_COLLECTIONS:
            try:
                points = await _scroll_collection(client, collection)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    log.warning("pruning_collection_missing", collection=collection)
                    continue
                raise

            for point in points:
                if _is_pruning_candidate(point):
                    payload = point.get("payload") or {}
                    age = _age_days(payload)
                    candidates.append({
                        "collection": collection,
                        "point_id": point["id"],
                        "age_days": age,
                        "score": payload.get("score"),
                        "text_preview": str(payload.get("text", ""))[:200],
                        "last_validated_at": payload.get("last_validated_at"),
                        "captured_at": payload.get("captured_at"),
                    })

            log.info(
                "pruning_collection_scanned",
                collection=collection,
                total_points=len(points),
                candidates=sum(1 for c in candidates if c["collection"] == collection),
            )

    if not candidates:
        log.info("pruning_no_candidates_found")
        return candidates

    log.info("pruning_candidates_total", count=len(candidates))

    if effective_dry_run:
        print(f"\n[DRY RUN] {len(candidates)} candidate(s) would be flagged:\n")
        for c in candidates:
            print(
                f"  [{c['collection']}] id={c['point_id']} "
                f"age={c['age_days']:.0f}d score={c['score']}\n"
                f"    \"{c['text_preview'][:100]}\"\n"
            )
    else:
        await _post_to_kno01(candidates)

    return candidates


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ph1917 nightly pruning job")
    parser.add_argument("--dry-run", action="store_true", help="Print candidates without posting to KNO-01")
    args = parser.parse_args()

    asyncio.run(run_pruning_job(dry_run=args.dry_run or PRUNING_DRY_RUN))
