"""
Chat Memory — MongoDB Atlas Persistent Sessions
=================================================
Stores conversation history in a `chat_sessions` collection so sessions
survive server restarts and redeploys.

Each document:
  {
    "_id": "uuid-string",
    "user_id": "uuid-string",          # owner; added for per-user isolation
    "messages": [{"role": "user"|"assistant", "content": "..."}],
    "activity": [...],
    "created_at": datetime,
    "updated_at": datetime
  }

Every method takes an optional ``user_id``. When supplied it is folded into the
query filter, so a caller cannot accidentally read or mutate another user's
session by passing its ID. Leaving it as ``None`` preserves the original
unscoped behaviour, which the test-suite relies on; `src/app.py` always passes
it on authenticated routes.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

# Sessions ingested before multi-user support carry no `user_id`. Because every
# scoped helper filters on it, those documents are invisible to all
# authenticated users rather than being handed to whichever account asks first.
# Backfill them with an explicit owner before relying on old data.


class ChatMemory:
    """Persistent chat session store backed by MongoDB Atlas."""

    COLLECTION = "chat_sessions"

    def __init__(self, db):
        """
        Args:
            db: A pymongo.database.Database instance (e.g. mongo_client["legal_rag"]).
        """
        self.col = db[self.COLLECTION]

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------
    def ensure_indexes(self) -> None:
        """Create the indexes the per-user query patterns rely on. Idempotent."""
        try:
            self.col.create_index("user_id")
            self.col.create_index([("user_id", 1), ("updated_at", -1)])
        except Exception as exc:  # pragma: no cover - index creation is best-effort
            print(f"⚠️ Could not create chat_sessions indexes: {exc}")

    # ------------------------------------------------------------------
    # Ownership
    # ------------------------------------------------------------------
    def owns_session(self, session_id: str, user_id: str) -> bool:
        """Whether *user_id* may operate on *session_id*.

        Strict by design: a session that does not exist is NOT claimable. This
        matters because ``/api/chat`` accepts a client-supplied session_id, so a
        permissive rule would let any authenticated user adopt an arbitrary
        identifier and become its owner. Sessions are persisted with their owner
        by ``POST /api/session``, so existence implies known ownership.
        """
        doc = self.col.find_one({"_id": session_id}, {"user_id": 1})
        if doc is None:
            return False
        return doc.get("user_id") == user_id

    def get_session_ids(self, user_id: str) -> list[str]:
        """All session IDs belonging to *user_id*, for scoping chunk/KG queries."""
        return [doc["_id"] for doc in self.col.find({"user_id": user_id}, {"_id": 1})]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def has_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """Check if a session exists in the database by its ID."""
        query = {"_id": session_id}
        if user_id is not None:
            query["user_id"] = user_id
        return self.col.find_one(query, {"_id": 1}) is not None

    def create_session(
        self,
        session_id: str | None = None,
        title: str | None = None,
        user_id: Optional[str] = None,
    ) -> str:
        """Create a new empty session. Returns the session ID."""
        sid = session_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        document = {
            "_id": sid,
            "title": title or "New Session",
            "messages": [],
            "activity": [{"title": "Session initialized", "status": "Info", "timestamp": now}],
            "created_at": now,
            "updated_at": now,
        }
        if user_id is not None:
            document["user_id"] = user_id
        self.col.insert_one(document)
        return sid

    def get_history(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """Return the last *limit* messages for a session (oldest-first)."""
        query = {"_id": session_id}
        if user_id is not None:
            query["user_id"] = user_id
        doc = self.col.find_one(
            query,
            {"messages": {"$slice": -limit}},
        )
        if doc is None:
            return []
        return doc.get("messages", [])

    def append(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Push a single message onto the session's history."""
        query = {"_id": session_id}
        if user_id is not None:
            query["user_id"] = user_id
        self.col.update_one(
            query,
            {
                "$push": {"messages": {"role": role, "content": content}},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

    def list_sessions(
        self,
        user_id: Optional[str] = None,
        limit: int = 20,
        include_empty: bool = True,
    ) -> list[dict]:
        """Return the most recently updated sessions, scoped to *user_id* when given.

        Pass ``include_empty=False`` to hide sessions that were created but never
        used. Ownership is persisted eagerly by ``POST /api/session``, so the
        client can create one on page load; without this filter those empty
        shells would crowd out the user's real history.
        """
        query = {}
        if user_id is not None:
            query["user_id"] = user_id
        if not include_empty:
            query["messages.0"] = {"$exists": True}
        cursor = self.col.find(
            query,
            {"messages": 0},  # exclude messages to keep response small
        ).sort("updated_at", -1).limit(limit)
        return [
            {
                "session_id": doc["_id"],
                "title": doc.get("title"),
                "created_at": doc.get("created_at", "").isoformat() if doc.get("created_at") else None,
                "updated_at": doc.get("updated_at", "").isoformat() if doc.get("updated_at") else None,
            }
            for doc in cursor
        ]

    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a session. Returns True if it existed and was in scope."""
        query = {"_id": session_id}
        if user_id is not None:
            query["user_id"] = user_id
        result = self.col.delete_one(query)
        return result.deleted_count > 0

    def rename_session(
        self,
        session_id: str,
        new_title: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """Rename a session. Returns True if it existed and was in scope."""
        query = {"_id": session_id}
        if user_id is not None:
            query["user_id"] = user_id
        result = self.col.update_one(query, {"$set": {"title": new_title}})
        return result.modified_count > 0

    def log_activity(
        self,
        session_id: str,
        title: str,
        status: str = "Info",
        user_id: Optional[str] = None,
    ) -> None:
        """Log an activity for the session."""
        query = {"_id": session_id}
        if user_id is not None:
            query["user_id"] = user_id
        self.col.update_one(
            query,
            {
                "$push": {
                    "activity": {
                        "title": title,
                        "status": status,
                        "timestamp": datetime.now(timezone.utc),
                    }
                }
            },
        )
