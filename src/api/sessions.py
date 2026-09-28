"""
Session lifecycle routes
=========================
Create, list, read, rename, and delete a user's chat sessions.

Deleting a session cascades to everything indexed under it, so chunks and
Knowledge Graph nodes never outlive the conversation they belong to.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.core.common import config
from src.core.common.security import get_current_user
from src.api.deps import get_engine, get_memory, require_owned_session

router = APIRouter(prefix="/api", tags=["sessions"])


class SessionRenameRequest(BaseModel):
    title: str


@router.post("/session")
def create_session(
    user: dict = Depends(get_current_user),
    memory=Depends(get_memory),
):
    """Create a session owned by the caller and return its ID.

    The document is persisted immediately with its owner. Deferring that would
    leave a window in which an arbitrary client-supplied session_id could be
    claimed by whoever sent it first.
    """
    return {"session_id": memory.create_session(user_id=user["id"])}


@router.get("/sessions")
def list_sessions(
    user: dict = Depends(get_current_user),
    memory=Depends(get_memory),
):
    """List the caller's sessions that have actually been used."""
    return {"sessions": memory.list_sessions(user_id=user["id"], include_empty=False)}


@router.get("/session/{session_id}")
def get_session(
    session_id: str,
    user: dict = Depends(get_current_user),
    memory=Depends(get_memory),
):
    """Return the full message history for one of the caller's sessions."""
    session_id = require_owned_session(session_id, user, memory)

    doc = memory.col.find_one(
        {"_id": session_id, "user_id": user["id"]},
        {"messages": {"$slice": -50}, "activity": 1},
    )
    if doc is None:
        return {"session_id": session_id, "messages": [], "activity": []}

    return {
        "session_id": session_id,
        "messages": doc.get("messages", []),
        "activity": doc.get("activity", []),
    }


@router.put("/session/{session_id}/rename")
def rename_session(
    session_id: str,
    request: SessionRenameRequest,
    user: dict = Depends(get_current_user),
    memory=Depends(get_memory),
):
    """Rename one of the caller's sessions."""
    session_id = require_owned_session(session_id, user, memory)
    memory.rename_session(session_id, request.title, user_id=user["id"])
    memory.log_activity(
        session_id, f"Session renamed to '{request.title}'", "Info", user_id=user["id"]
    )
    return {"status": "renamed", "session_id": session_id, "title": request.title}


@router.delete("/session/{session_id}")
def delete_session(
    session_id: str,
    user: dict = Depends(get_current_user),
    memory=Depends(get_memory),
    engine=Depends(get_engine),
):
    """Delete a session and every chunk and graph record indexed under it."""
    session_id = require_owned_session(session_id, user, memory)
    memory.delete_session(session_id, user_id=user["id"])

    if getattr(engine, "db", None) is not None:
        engine.db[config.CHUNKS_COLLECTION].delete_many({"metadata.session_id": session_id})
        engine.db[config.KG_NODES_COLLECTION].delete_many({"session_id": session_id})
        engine.db[config.KG_EDGES_COLLECTION].delete_many({"session_id": session_id})

    return {"status": "deleted", "session_id": session_id}
