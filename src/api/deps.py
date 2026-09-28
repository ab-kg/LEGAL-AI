"""
Shared FastAPI dependencies for the API layer.

These replace the module-level ``engine``/``memory`` globals that used to live
in ``src/app.py``. Long-lived resources are now attached to ``app.state`` during
startup and resolved here, so routers never reach for a global.
"""

from fastapi import HTTPException, Request, status

from src.core.common.utils import sanitize_session_id
from src.core.rag.chat_memory import ChatMemory

# ─── Resource accessors ──────────────────────────────────────────────

def get_db(request: Request):
    """The MongoDB handle opened at startup, or 503 if it is not ready."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not ready.",
        )
    return db

def get_engine(request: Request):
    """The RAG engine, or 503 while it is still booting."""
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Engine still booting. Try again shortly.",
        )
    return engine

def get_memory(request: Request) -> ChatMemory:
    """The session store, or 503 when MongoDB is unavailable."""
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat memory disabled.",
        )
    return memory

# ─── Ownership ───────────────────────────────────────────────────────

def require_owned_session(
    session_id: str,
    user: dict,
    memory: ChatMemory,
) -> str:
    """Return the sanitized session ID, or 404 if *user* does not own it.

    404 rather than 403 on purpose: a 403 would confirm the session exists to
    someone who is not its owner, turning the endpoint into an ID oracle.
    """
    clean = sanitize_session_id(session_id)
    if not clean:
        raise HTTPException(status_code=400, detail="Missing session_id.")
    if not memory.owns_session(clean, user["id"]):
        raise HTTPException(status_code=404, detail="Session not found.")
    return clean