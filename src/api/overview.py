"""
Dashboard routes
=================
Per-user activity feed and the metrics behind the overview page.

Both are scoped to the caller. Before per-user isolation these aggregated
across every session in the database, which leaked other users' activity.
"""

from fastapi import APIRouter, Depends, HTTPException

from src.core.common import config
from src.core.common.utils import sanitize_session_id
from src.core.common.security import get_current_user
from src.api.deps import get_engine, get_memory

router = APIRouter(prefix="/api", tags=["dashboard"])

@router.get("/activity")
@router.get("/activity/global", include_in_schema=False)
def recent_activity(user: dict = Depends(get_current_user), memory=Depends(get_memory)):
    """Latest activity across the caller's own sessions only."""
    activities = list(
        memory.col.aggregate(
            [
                {"$match": {"user_id": user["id"]}},
                {"$unwind": "$activity"},
                {"$sort": {"activity.timestamp": -1}},
                {"$limit": 20},
                {"$replaceRoot": {"newRoot": "$activity"}},
            ]
        )
    )

    for a in activities:
        if hasattr(a.get("timestamp"), "isoformat"):
            a["timestamp"] = a["timestamp"].isoformat()

    return {"activity": activities}


@router.get("/overview/summary")
def overview_summary(
    user: dict = Depends(get_current_user),
    engine=Depends(get_engine),
    memory=Depends(get_memory),
):
    """Contract and query metrics scoped to the caller's own sessions."""
    empty = {"total_contracts": 0, "session_distribution": [], "query_distribution": []}

    if engine.db is None:
        return empty

    session_ids = memory.get_session_ids(user["id"])
    if not session_ids:
        return empty

    try:
        chunks = engine.db[config.CHUNKS_COLLECTION]

        total_contracts = len(
            set(
                chunks.distinct(
                    "metadata.contract_id", {"metadata.session_id": {"$in": session_ids}}
                )
            )
        )

        session_distribution = _distribution_per_session(chunks, session_ids, memory, user)

        return {
            "total_contracts": total_contracts,
            "session_distribution": session_distribution,
            "query_distribution": _query_distribution(memory, user),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")


def _distribution_per_session(chunks, session_ids, memory, user) -> list[dict]:
    """Count distinct contracts per session, newest first."""
    results = list(
        chunks.aggregate(
            [
                {"$match": {"metadata.session_id": {"$in": session_ids}}},
                {
                    "$group": {
                        "_id": "$metadata.session_id",
                        "contracts": {"$addToSet": "$metadata.contract_id"},
                    }
                },
            ]
        )
    )

    titles = _session_titles(memory, user)

    distribution = []
    for doc in results:
        raw = doc.get("_id")
        sid = sanitize_session_id(str(raw) if raw is not None else "global")
        contracts = [c for c in doc.get("contracts", []) if c]
        distribution.append(
            {
                "session_id": sid,
                "title": titles.get(sid, "Global Context" if sid == "global" else sid[:8]),
                "contracts_count": len(contracts),
                "contracts": contracts,
            }
        )

    distribution.sort(key=lambda x: x["contracts_count"], reverse=True)
    return distribution


def _session_titles(memory, user) -> dict:
    """Map session ID -> display title for the caller's sessions."""
    titles = {}
    try:
        for res in memory.col.aggregate(
            [
                {"$match": {"user_id": user["id"]}},
                {"$sort": {"updated_at": -1}},
                {"$project": {"_id": 1, "title": 1}},
            ]
        ):
            sid = str(res["_id"])
            titles[sid] = res.get("title") or sid[:8]
    except Exception as e:
        print("Error fetching session titles:", e)
    return titles


def _query_distribution(memory, user, limit: int = 10) -> list[dict]:
    """User queries per session. Each exchange stores two messages, so divide by two."""
    titles = _session_titles(memory, user)

    distribution = []
    try:
        for res in memory.col.aggregate(
            [
                {"$match": {"user_id": user["id"]}},
                {"$sort": {"updated_at": -1}},
                {"$project": {"_id": 1, "title": 1, "query_count": {"$size": {"$ifNull": ["$messages", []]}}}},
            ]
        ):
            sid = str(res["_id"])
            # user + assistant = one exchange, so // 2 gives real query count.
            queries = max(0, res.get("query_count", 0) // 2)
            if queries > 0:
                distribution.append(
                    {
                        "session_id": sid,
                        "title": titles.get(sid) or sid[:8],
                        "query_count": queries,
                    }
                )
    except Exception as e:
        print("Error fetching query distribution:", e)

    return distribution[:limit]
