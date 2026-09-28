from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, File, status
from pydantic import BaseModel, Field
from typing import Optional
import os
import uuid

from src.core.common.utils import force_ipv4, sanitize_session_id
from src.core.rag_pipeline import LegalGraphRAG
from src.core.rag.chat_memory import ChatMemory
from src.core.common import config
from src.core.common.security import (
    create_access_token,
    create_user_record,
    get_current_user,
    hash_password,
    require_admin,
    validate_password,
    validate_username,
    verify_password,
)

# Ensure IPv4-only resolution before any network I/O
force_ipv4()

# ==========================================
# 🚀 LIFESPAN — auto-boot engine on startup
# ==========================================
engine: LegalGraphRAG | None = None
memory: ChatMemory | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the RAG engine and chat memory once when the server starts."""
    global engine, memory
    print("🚀 Booting LegalGraphRAG engine on startup...")
    engine = LegalGraphRAG()
    print("✅ Engine ready — accepting requests.")

    # Reuse the MongoDB connection the engine already opened
    if engine.db is not None:
        app.state.db = engine.db
        memory = ChatMemory(engine.db)
        memory.ensure_indexes()
        print("💬 Chat memory ready (MongoDB Atlas).")

        # Seed the admin account, if credentials are configured.
        if config.ADMIN_USERNAME and config.ADMIN_PASSWORD:
            users_col = engine.db[config.USERS_COLLECTION]
            admin = validate_username(config.ADMIN_USERNAME)
            if users_col.count_documents({"username": admin}) == 0:
                users_col.insert_one(
                    {
                        "_id": str(uuid.uuid4()),
                        "username": admin,
                        "password": hash_password(config.ADMIN_PASSWORD),
                        "role": "admin",
                    }
                )
                print(f"👤 Created default admin user: {admin}")
            else:
                print(f"👤 Admin user already present: {admin}")
        else:
            print("⚠️ ADMIN_USERNAME/ADMIN_PASSWORD not set — no admin seeded.")
    else:
        print("⚠️ No MongoDB — chat memory disabled (sessions are ephemeral).")
    yield
    print("🛑 Shutting down.")


from fastapi.middleware.cors import CORSMiddleware

# Explicit allowlist. A wildcard origin combined with credentials is rejected by
# browsers and would let any site on the internet call this API with a cookie.
ALLOWED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
    if origin.strip()
]

app = FastAPI(title="Legal AI GraphRAG API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if (
        path == "/"
        or path.endswith(".html")
        or path.endswith(".js")
        or path.endswith(".css")
    ):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ==========================================
# 📦 REQUEST / RESPONSE MODELS
# ==========================================

class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=72)


class SessionRenameRequest(BaseModel):
    title: str


# ==========================================
# 🔐 AUTH
# ==========================================

@app.post("/api/register", status_code=status.HTTP_201_CREATED)
def register(credentials: Credentials, request: Request):
    """Create an account and return a ready-to-use token."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready.")

    username = validate_username(credentials.username)
    validate_password(credentials.password)

    users_col = db[config.USERS_COLLECTION]
    if users_col.find_one({"username": username}):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username is already taken.",
        )

    create_user_record(db, config.USERS_COLLECTION, username, credentials.password, role="user")
    token = create_access_token(username, "user")
    return {"token": token, "username": username, "role": "user"}


@app.post("/api/login")
def login(credentials: Credentials, request: Request):
    """Authenticate against the users collection and issue a JWT."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready.")

    username = credentials.username.strip().lower()
    user = db[config.USERS_COLLECTION].find_one({"username": username})
    # Same message for unknown user and wrong password so the response cannot be
    # used to enumerate accounts.
    if user is None or not verify_password(credentials.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    role = user.get("role", "user")
    return {"token": create_access_token(username, role), "username": username, "role": role}


@app.get("/api/me")
def whoami(user: dict = Depends(get_current_user)):
    """Return the authenticated caller's identity."""
    return user


@app.get("/api/health")
def health_check():
    """Lightweight GET endpoint for Railway health checks. Deliberately public."""
    return {
        "status": "healthy",
        "engine_ready": engine is not None,
        "memory_enabled": memory is not None,
    }


# ==========================================
# 🔧 HELPERS
# ==========================================

def _require_memory() -> ChatMemory:
    if memory is None:
        raise HTTPException(status_code=503, detail="Chat memory disabled.")
    return memory


def require_owned_session(session_id: str, user: dict) -> str:
    """Return the sanitized session ID, or 404 if *user* does not own it.

    404 rather than 403 on purpose: a 403 would confirm the session exists to
    someone who is not its owner.
    """
    store = _require_memory()
    clean = sanitize_session_id(session_id)
    if not clean:
        raise HTTPException(status_code=400, detail="Missing session_id.")
    if not store.owns_session(clean, user["id"]):
        raise HTTPException(status_code=404, detail="Session not found.")
    return clean


def user_session_ids(user: dict) -> list[str]:
    """Session IDs owned by the caller, for scoping chunk and graph queries."""
    return _require_memory().get_session_ids(user["id"])


def _require_engine():
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine still booting. Try again shortly.")
    return engine


# ==========================================
# 🔧 SESSION ENDPOINTS
# ==========================================

@app.post("/api/session")
def create_session(user: dict = Depends(get_current_user)):
    """Create a new chat session owned by the caller and return its ID.

    The document is persisted immediately with its owner. Deferring that would
    leave a window in which an arbitrary client-supplied session_id could be
    claimed by whoever sent it first.
    """
    store = _require_memory()
    sid = store.create_session(user_id=user["id"])
    return {"session_id": sid}


@app.get("/api/sessions")
def list_sessions(user: dict = Depends(get_current_user)):
    """List the caller's own sessions that have actually been used."""
    if not memory:
        return {"sessions": [], "note": "Memory disabled — no MongoDB."}
    return {
        "sessions": memory.list_sessions(user_id=user["id"], include_empty=False)
    }


@app.get("/api/activity")
@app.get("/api/activity/global", include_in_schema=False)
def recent_activity(user: dict = Depends(get_current_user)):
    """Latest activity across the caller's own sessions only."""
    if not memory:
        return {"activity": []}

    pipeline = [
        {"$match": {"user_id": user["id"]}},
        {"$unwind": "$activity"},
        {"$sort": {"activity.timestamp": -1}},
        {"$limit": 20},
        {"$replaceRoot": {"newRoot": "$activity"}},
    ]
    activities = list(memory.col.aggregate(pipeline))

    for a in activities:
        if "timestamp" in a and hasattr(a["timestamp"], "isoformat"):
            a["timestamp"] = a["timestamp"].isoformat()

    return {"activity": activities}


@app.delete("/api/session/{session_id}")
def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    """Delete one of the caller's sessions and everything indexed under it."""
    session_id = require_owned_session(session_id, user)
    store = _require_memory()
    store.delete_session(session_id, user_id=user["id"])

    if engine and engine.db is not None:
        engine.db[config.CHUNKS_COLLECTION].delete_many({"metadata.session_id": session_id})
        engine.db[config.KG_NODES_COLLECTION].delete_many({"session_id": session_id})
        engine.db[config.KG_EDGES_COLLECTION].delete_many({"session_id": session_id})

    return {"status": "deleted", "session_id": session_id}


@app.put("/api/session/{session_id}/rename")
def rename_session(
    session_id: str,
    request: SessionRenameRequest,
    user: dict = Depends(get_current_user),
):
    """Rename one of the caller's sessions."""
    session_id = require_owned_session(session_id, user)
    store = _require_memory()
    store.rename_session(session_id, request.title, user_id=user["id"])
    store.log_activity(
        session_id, f"Session renamed to '{request.title}'", "Info", user_id=user["id"]
    )
    return {"status": "renamed", "session_id": session_id, "title": request.title}


@app.get("/api/session/{session_id}")
def get_session(session_id: str, user: dict = Depends(get_current_user)):
    """Return the full message history for one of the caller's sessions."""
    session_id = require_owned_session(session_id, user)
    store = _require_memory()

    doc = store.col.find_one(
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


@app.post("/api/session/{session_id}/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_pdf(
    session_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """Ingest a contract PDF into one of the caller's sessions."""
    _require_engine()
    session_id = require_owned_session(session_id, user)
    store = _require_memory()

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported.")

    try:
        pdf_bytes = await file.read()
        if not store.has_session(session_id, user_id=user["id"]):
            store.create_session(
                session_id, title=f"Upload: {file.filename}", user_id=user["id"]
            )
        store.log_activity(
            session_id, f"Ingested PDF: {file.filename}", "Success", user_id=user["id"]
        )

        result = engine.ingest_pdf(file.filename, pdf_bytes, session_id)

        store.append(
            session_id,
            "assistant",
            f"✅ **Successfully uploaded and indexed {file.filename}**\n\nHow can I help you analyze it?",
            user_id=user["id"],
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@app.get("/api/session/{session_id}/chunks")
def get_session_chunks(session_id: str, user: dict = Depends(get_current_user)):
    """Metadata and text snippets for documents indexed in this session."""
    eng = _require_engine()
    session_id = require_owned_session(session_id, user)

    if eng.db is None:
        return {
            "session_id": session_id,
            "has_pdf": False,
            "contracts": [],
            "chunks_count": 0,
            "chunks": [],
            "note": "MongoDB is not connected. Local fallback mode has no PDF storage.",
        }

    try:
        cursor = eng.db[config.CHUNKS_COLLECTION].find(
            {"metadata.session_id": session_id},
            {"embedding": 0},
        )
        chunks = list(cursor)

        contracts = list(
            set(
                doc.get("metadata", {}).get("contract_id", "Unknown")
                for doc in chunks
                if doc.get("metadata")
            )
        )

        formatted_chunks = []
        for doc in chunks:
            metadata = doc.get("metadata", {})
            text = doc.get("text", "") or ""
            formatted_chunks.append(
                {
                    "chunk_id": str(doc.get("_id")),
                    "contract_id": metadata.get("contract_id", "Unknown"),
                    "chunk_index": metadata.get("chunk_index", 0),
                    "word_count": metadata.get("word_count", 0),
                    "text_snippet": text[:200] + ("..." if len(text) > 200 else ""),
                }
            )

        return {
            "session_id": session_id,
            "has_pdf": len(chunks) > 0,
            "contracts": contracts,
            "chunks_count": len(chunks),
            "chunks": formatted_chunks,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")


@app.get("/api/session/{session_id}/graph")
def get_session_graph(session_id: str, user: dict = Depends(get_current_user)):
    """Knowledge Graph nodes and edges extracted for this session."""
    eng = _require_engine()
    session_id = require_owned_session(session_id, user)
    store = _require_memory()

    if eng.db is None:
        return {
            "session_id": session_id,
            "nodes": [],
            "edges": [],
            "note": "MongoDB is not connected. Local fallback mode has no PDF storage.",
        }

    try:
        nodes = list(eng.db[config.KG_NODES_COLLECTION].find({"session_id": session_id}))
        edges = list(eng.db[config.KG_EDGES_COLLECTION].find({"session_id": session_id}))

        formatted_nodes = []
        for n in nodes:
            formatted_n = n.copy()
            formatted_n["_id"] = str(n["_id"])
            formatted_nodes.append(formatted_n)

        formatted_edges = []
        for e in edges:
            formatted_e = e.copy()
            if "_id" in formatted_e:
                formatted_e["_id"] = str(formatted_e["_id"])
            formatted_edges.append(formatted_e)

        if len(formatted_nodes) > 0:
            try:
                store.log_activity(
                    session_id, "Visualized Knowledge Graph", "Info", user_id=user["id"]
                )
            except Exception as e:
                print(f"Failed to log activity: {e}")

        return {
            "session_id": session_id,
            "nodes_count": len(formatted_nodes),
            "edges_count": len(formatted_edges),
            "nodes": formatted_nodes,
            "edges": formatted_edges,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")


@app.get("/api/session/{session_id}/contracts")
def get_session_contracts_summary(session_id: str, user: dict = Depends(get_current_user)):
    """Structured metadata for the contracts indexed in this session."""
    eng = _require_engine()
    session_id = require_owned_session(session_id, user)

    if eng.db is None:
        return {
            "session_id": session_id,
            "contracts": [],
            "note": "MongoDB is not connected. Local fallback mode has no PDF storage.",
        }

    try:
        contracts = list(
            eng.db[config.KG_NODES_COLLECTION].find(
                {"entity_type": "Contract", "session_id": session_id}
            )
        )
        formatted_contracts = [
            {
                "contract_id": str(c["_id"]),
                "summary": c.get("summary"),
                "contract_type": c.get("contract_type"),
                "effective_date": c.get("effective_date"),
                "contract_scope": c.get("contract_scope"),
                "duration": c.get("duration"),
                "end_date": c.get("end_date"),
                "total_amount": c.get("total_amount"),
            }
            for c in contracts
        ]
        return {
            "session_id": session_id,
            "contracts_count": len(formatted_contracts),
            "contracts": formatted_contracts,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")


@app.get("/api/overview/summary")
def get_overview_summary(user: dict = Depends(get_current_user)):
    """Metrics scoped to the caller's own sessions and documents."""
    eng = _require_engine()
    store = _require_memory()

    if eng.db is None:
        return {"total_contracts": 0, "session_distribution": [], "query_distribution": []}

    session_ids = store.get_session_ids(user["id"])
    if not session_ids:
        return {"total_contracts": 0, "session_distribution": [], "query_distribution": []}

    try:
        chunks = eng.db[config.CHUNKS_COLLECTION]

        total_contracts = len(
            set(
                chunks.distinct(
                    "metadata.contract_id", {"metadata.session_id": {"$in": session_ids}}
                )
            )
        )

        pipeline = [
            {"$match": {"metadata.session_id": {"$in": session_ids}}},
            {
                "$group": {
                    "_id": "$metadata.session_id",
                    "contracts": {"$addToSet": "$metadata.contract_id"},
                }
            },
        ]
        aggregation_results = list(chunks.aggregate(pipeline))

        session_titles = {}
        try:
            title_pipeline = [
                {"$match": {"user_id": user["id"]}},
                {"$sort": {"updated_at": -1}},
                {
                    "$project": {
                        "_id": 1,
                        "title": 1,
                        "query_count": {"$size": {"$ifNull": ["$messages", []]}},
                    }
                },
            ]
            for res in store.col.aggregate(title_pipeline):
                sid = str(res["_id"])
                session_titles[sid] = res.get("title") or sid[:8]
                q_count = max(0, res.get("query_count", 0) // 2)
                if q_count > 0:
                    session_titles.setdefault("__qcount__" + sid, q_count)
        except Exception as e:
            print("Error fetching query distribution:", e)

        query_distribution = [
            {
                "session_id": sid[len("__qcount__"):],
                "title": session_titles.get(sid[len("__qcount__"):], "Session"),
                "query_count": count,
            }
            for sid, count in session_titles.items()
            if sid.startswith("__qcount__")
        ][:10]

        session_distribution = []
        for doc in aggregation_results:
            raw_sid = doc.get("_id")
            sid = str(raw_sid) if raw_sid is not None else "global"
            sid = sanitize_session_id(sid)
            valid_contracts = [c for c in doc.get("contracts", []) if c]
            session_distribution.append(
                {
                    "session_id": sid,
                    "title": session_titles.get(
                        sid, "Global Context" if sid == "global" else sid[:8]
                    ),
                    "contracts_count": len(valid_contracts),
                    "contracts": valid_contracts,
                }
            )

        session_distribution.sort(key=lambda x: x["contracts_count"], reverse=True)

        return {
            "total_contracts": total_contracts,
            "session_distribution": session_distribution,
            "query_distribution": query_distribution,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")


@app.post("/api/chat")
def chat(request: ChatRequest, user: dict = Depends(get_current_user)):
    _require_engine()
    store = _require_memory()

    raw_session_id = request.session_id
    if raw_session_id:
        session_id_clean = sanitize_session_id(raw_session_id)
        if not store.owns_session(session_id_clean, user["id"]):
            raise HTTPException(status_code=404, detail="Session not found.")
    else:
        # No session referenced: start a new one, already owned by the caller.
        session_id_clean = store.create_session(user_id=user["id"])
    session_id_to_search = session_id_clean

    history = store.get_history(session_id_clean, user_id=user["id"])

    try:
        answer, contexts, triplets = engine.answer_query(
            request.query, chat_history=history, session_id=session_id_to_search
        )

        if not store.has_session(session_id_clean, user_id=user["id"]):
            title = request.query[:40] + ("..." if len(request.query) > 40 else "")
            store.create_session(session_id_clean, title=title, user_id=user["id"])
        store.append(session_id_clean, "user", request.query, user_id=user["id"])
        store.append(session_id_clean, "assistant", answer, user_id=user["id"])
        store.log_activity(
            session_id_clean, f"Query: '{request.query[:30]}...'", "Info", user_id=user["id"]
        )

        return {
            "answer": answer,
            "contexts": contexts,
            "triplets": triplets,
            "session_id": session_id_clean,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        trace_str = traceback.format_exc()
        print(f"❌ Chat Error: {trace_str}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/admin/users")
def admin_list_users(user: dict = Depends(require_admin)):
    """Administrative view of every account. Admin only."""
    db = engine.db if engine else None
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready.")
    users = db[config.USERS_COLLECTION].find({}, {"password": 0})
    return {
        "users": [
            {
                "username": u["username"],
                "role": u.get("role", "user"),
                "created_at": u["created_at"].isoformat() if u.get("created_at") else None,
            }
            for u in users
        ]
    }


# ==========================================
# 🌐 FRONTEND
# ==========================================
from fastapi.staticfiles import StaticFiles

frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    # Import as `src.app` so it works from the project root; running this file
    # directly would otherwise put src/ on sys.path and break the src.* imports.
    uvicorn.run("src.app:app", host="0.0.0.0", port=port)
