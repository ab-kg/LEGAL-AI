"""
Chat routes
============
The conversational endpoint. Owns the whole turn: resolve or create a session,
load history, run hybrid retrieval, and persist both sides of the exchange.
"""

import traceback

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from src.core.common.utils import sanitize_session_id
from src.core.common.security import get_current_user
from src.api.deps import get_engine, get_memory

router = APIRouter(prefix="/api", tags=["chat"])

class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None

@router.post("/chat")
def chat(
    request: ChatRequest,
    user: dict = Depends(get_current_user),
    engine=Depends(get_engine),
    memory=Depends(get_memory),
):
    engine.answer_query  # fail fast with 503 before touching storage

    raw_session_id = request.session_id
    if raw_session_id:
        session_id = sanitize_session_id(raw_session_id)
        # Strict ownership: an unknown or foreign session is never adopted.
        if not memory.owns_session(session_id, user["id"]):
            raise HTTPException(status_code=404, detail="Session not found.")
    else:
        # No session referenced, so start one already owned by the caller.
        session_id = memory.create_session(user_id=user["id"])

    history = memory.get_history(session_id, user_id=user["id"])

    try:
        answer, contexts, triplets = engine.answer_query(
            request.query, chat_history=history, session_id=session_id
        )

        if not memory.has_session(session_id, user_id=user["id"]):
            title = request.query[:40] + ("..." if len(request.query) > 40 else "")
            memory.create_session(session_id, title=title, user_id=user["id"])

        memory.append(session_id, "user", request.query, user_id=user["id"])
        memory.append(session_id, "assistant", answer, user_id=user["id"])
        memory.log_activity(
            session_id, f"Query: '{request.query[:30]}...'", "Info", user_id=user["id"]
        )

        return {
            "answer": answer,
            "contexts": contexts,
            "triplets": triplets,
            "session_id": session_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Chat Error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
