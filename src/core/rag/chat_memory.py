"""
Chat Memory — MongoDB Atlas Persistent Sessions
=================================================
Stores conversation history in a `chat_sessions` collection so sessions
survive server restarts and redeploys.

Each document:
  {
    "_id": "uuid-string",
    "messages": [{"role": "user"|"assistant", "content": "..."}],
    "created_at": datetime,
    "updated_at": datetime
  }
"""

import uuid
from datetime import datetime, timezone


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
    # CRUD
    # ------------------------------------------------------------------

    def has_session(self, session_id: str) -> bool:
        """Check if a session exists in the database by its ID."""
        return self.col.find_one({"_id": session_id}, {"_id": 1}) is not None

    def create_session(self, session_id: str | None = None, title: str | None = None) -> str:
        """Create a new empty session. Returns the session ID."""
        sid = session_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        self.col.insert_one({
            "_id": sid ,
            "title": title or "New Session" ,
            "messages": [],
            "activity": [{"title": "Session initialized", "status": "Info", "timestamp": now}],
            "created_at": now,
            "updated_at": now,
        })
        return sid

    def get_history(self, session_id: str, limit: int = 10) -> list[dict]:
        """Return the last *limit* messages for a session (oldest-first)."""
        doc = self.col.find_one(
            {"_id": session_id},
            {"messages": {"$slice": -limit}},
        )
        if doc is None:
            return []
        return doc.get("messages", [])

    def append(self, session_id: str, role: str, content: str) -> None:
        """Push a single message onto the session's history."""
        self.col.update_one(
            {"_id": session_id},
            {
                "$push": {"messages": {"role": role, "content": content}},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

    def list_sessions(self, limit: int = 20) -> list[dict]:
        """Return the most recently updated sessions (for debugging/API)."""
        cursor = self.col.find(
            {},
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

    def delete_session(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed."""
        result = self.col.delete_one({"_id": session_id})
        return result.deleted_count > 0

    def rename_session(self, session_id: str, new_title: str) -> bool:
        """Rename a session. Returns True if it existed."""
        result = self.col.update_one(
            {"_id": session_id} ,
            {"$set": {"title": new_title}}
        )
        return result.modified_count > 0

    def log_activity(self, session_id: str, title: str, status: str = "Info") -> None:
        """Log an activity for the session."""
        self.col.update_one(
            {"_id": session_id},
            {
                "$push": {
                    "activity": {
                        "title": title,
                        "status": status,
                        "timestamp": datetime.now(timezone.utc)
                    }
                }
            }
        )
