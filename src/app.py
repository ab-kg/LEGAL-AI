from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File, status
from pydantic import BaseModel
from typing import Optional
import os
import uuid

from src.core.common.utils import force_ipv4, sanitize_session_id
from src.core.rag_pipeline import LegalGraphRAG
from src.core.rag.chat_memory import ChatMemory
from src.core.common import config

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
        memory = ChatMemory(engine.db)
        print("💬 Chat memory ready (MongoDB Atlas).")
    else:
        print("⚠️ No MongoDB — chat memory disabled (sessions are ephemeral).")

    yield
    print("🛑 Shutting down.")

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Legal AI GraphRAG API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.endswith(".html") or request.url.path.endswith(".js") or request.url.path.endswith(".css"):
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


# ==========================================
# 🔧 ENDPOINTS
# ==========================================

@app.get("/api/health")
def health_check():
    """Lightweight GET endpoint for Railway health checks."""
    return {
        "status": "healthy",
        "engine_ready": engine is not None,
        "memory_enabled": memory is not None,
    }


@app.post("/api/session")
def create_session():
    """Create a new chat session and return its unique ID without writing to DB until first use."""
    session_id = str(uuid.uuid4())
    return {"session_id": session_id}


@app.get("/api/sessions")
def list_sessions():
    """List the most recently updated sessions (for debugging)."""
    if not memory:
        return {"sessions": [], "note": "Memory disabled — no MongoDB."}
    return {"sessions": memory.list_sessions()}

@app.get("/api/activity/global")
def global_activity():
    """Fetch the latest activity from all sessions."""
    if not memory:
        return {"activity": []}
    
    # Aggregate to pull all 'activity' arrays, unwind, sort by timestamp descending, and take the top 20
    pipeline = [
        {"$unwind": "$activity"},
        {"$sort": {"activity.timestamp": -1}},
        {"$limit": 20},
        {"$replaceRoot": {"newRoot": "$activity"}}
    ]
    activities = list(memory.col.aggregate(pipeline))
    
    # Convert datetimes to isoformat string
    for a in activities:
        if "timestamp" in a and hasattr(a["timestamp"], "isoformat"):
            a["timestamp"] = a["timestamp"].isoformat()
            
    return {"activity": activities}

@app.delete("/api/session/{session_id}")
def delete_session(session_id: str):
    """Delete a session completely."""
    session_id = sanitize_session_id(session_id)
    if memory:
        memory.delete_session(session_id)
        
    if engine and engine.db is not None:
        engine.db[config.CHUNKS_COLLECTION].delete_many({"metadata.session_id": session_id})
        engine.db[config.KG_NODES_COLLECTION].delete_many({"session_id": session_id})
        engine.db[config.KG_EDGES_COLLECTION].delete_many({"session_id": session_id})
        
    return {"status": "deleted", "session_id": session_id}

class SessionRenameRequest(BaseModel):
    title: str

@app.put("/api/session/{session_id}/rename")
def rename_session(session_id: str, request: SessionRenameRequest):
    """Rename a session."""
    session_id = sanitize_session_id(session_id)
    if memory:
        memory.rename_session(session_id, request.title)
        memory.log_activity(session_id, f"Session renamed to '{request.title}'", "Info")
    return {"status": "renamed", "session_id": session_id, "title": request.title}


@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    """Return the full message history for a session."""
    session_id = sanitize_session_id(session_id)
    if not memory:
        raise HTTPException(status_code=503, detail="Chat memory disabled.")
    
    doc = memory.col.find_one({"_id": session_id}, {"messages": {"$slice": -50}, "activity": 1})
    if doc is None:
        return {"session_id": session_id, "messages": [], "activity": []}
        
    return {
        "session_id": session_id, 
        "messages": doc.get("messages", []),
        "activity": doc.get("activity", [])
    }


@app.post("/api/session/{session_id}/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_pdf(session_id: str, file: UploadFile = File(...)):
    """Receives a contract PDF, extracts its text, embeds, and vector indexes it for a session."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine still booting. Try again shortly.")
        
    session_id = sanitize_session_id(session_id)
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400, 
            detail="Only PDF uploads are supported."
        )
    
    try:
        pdf_bytes = await file.read()
        
        if memory:
            if not memory.has_session(session_id):
                memory.create_session(session_id, title=f"Upload: {file.filename}")
            memory.log_activity(session_id, f"Ingested PDF: {file.filename}", "Success")
            
        # Call RAG engine to ingest
        result = engine.ingest_pdf(file.filename, pdf_bytes, session_id)
        
        # Add a welcome message to the chat history so the user knows the file was uploaded
        if memory:
            memory.append(
                session_id, 
                "assistant", 
                f"✅ **Successfully uploaded and indexed {file.filename}**\n\nHow can I help you analyze it?"
            )
            
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ingestion failed: {str(e)}"
        )


@app.get("/api/session/{session_id}/chunks")
def get_session_chunks(session_id: str):
    """Verify if a session has ingested PDF chunks and return metadata & text snippets."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine still booting. Try again shortly.")
    
    session_id = sanitize_session_id(session_id)
    
    if engine.db is None:
        return {
            "session_id": session_id,
            "has_pdf": False,
            "contracts": [],
            "chunks_count": 0,
            "chunks": [],
            "note": "MongoDB is not connected. Local fallback mode has no PDF storage."
        }
    
    try:
        cursor = engine.db[config.CHUNKS_COLLECTION].find(
            {"metadata.session_id": session_id},
            {"embedding": 0}
        )
        chunks = list(cursor)
        
        contracts = list(set(
            doc.get("metadata", {}).get("contract_id", "Unknown")
            for doc in chunks if doc.get("metadata")
        ))
        
        formatted_chunks = []
        for doc in chunks:
            metadata = doc.get("metadata", {})
            formatted_chunks.append({
                "chunk_id": str(doc.get("_id")),
                "contract_id": metadata.get("contract_id", "Unknown"),
                "chunk_index": metadata.get("chunk_index", 0),
                "word_count": metadata.get("word_count", 0),
                "text_snippet": doc.get("text", "")[:200] + ("..." if len(doc.get("text", "")) > 200 else "")
            })
        
        return {
            "session_id": session_id,
            "has_pdf": len(chunks) > 0,
            "contracts": contracts,
            "chunks_count": len(chunks),
            "chunks": formatted_chunks
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")


@app.get("/api/session/{session_id}/graph")
def get_session_graph(session_id: str):
    """Verify if a session has extracted KG elements and return nodes and edges."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine still booting. Try again shortly.")
    
    session_id = sanitize_session_id(session_id)
    
    if engine.db is None:
        return {
            "session_id": session_id,
            "nodes": [],
            "edges": [],
            "note": "MongoDB is not connected. Local fallback mode has no PDF storage."
        }
        
    try:
        nodes = list(engine.db[config.KG_NODES_COLLECTION].find({"session_id": session_id}))
        edges = list(engine.db[config.KG_EDGES_COLLECTION].find({"session_id": session_id}))
        
        # Format nodes and edges for JSON serialization (clean BSON ObjectIds to string)
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
            
        if memory and len(formatted_nodes) > 0:
            try:
                memory.log_activity(session_id, "Visualized Knowledge Graph", "Info")
            except Exception as e:
                print(f"Failed to log activity: {e}")
            
        return {
            "session_id": session_id,
            "nodes_count": len(formatted_nodes),
            "edges_count": len(formatted_edges),
            "nodes": formatted_nodes,
            "edges": formatted_edges
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")


@app.get("/api/session/{session_id}/contracts")
def get_session_contracts_summary(session_id: str):
    """Retrieve structured metadata and summaries of all contracts ingested in this session."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine still booting. Try again shortly.")
    
    session_id = sanitize_session_id(session_id)
    
    if engine.db is None:
        return {
            "session_id": session_id,
            "contracts": [],
            "note": "MongoDB is not connected. Local fallback mode has no PDF storage."
        }
        
    try:
        contracts = list(engine.db[config.KG_NODES_COLLECTION].find(
            {"entity_type": "Contract", "session_id": session_id}
        ))
        
        formatted_contracts = []
        for c in contracts:
            formatted_contracts.append({
                "contract_id": str(c["_id"]),
                "summary": c.get("summary"),
                "contract_type": c.get("contract_type"),
                "effective_date": c.get("effective_date"),
                "contract_scope": c.get("contract_scope"),
                "duration": c.get("duration"),
                "end_date": c.get("end_date"),
                "total_amount": c.get("total_amount")
            })
            
        return {
            "session_id": session_id,
            "contracts_count": len(formatted_contracts),
            "contracts": formatted_contracts
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")


@app.get("/api/overview/summary")
def get_global_overview_summary():
    """Retrieve global metrics for the overview page: total contracts ingested and a distribution of contracts by session."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine still booting. Try again shortly.")
        
    if engine.db is None:
        return {
            "total_contracts": 0,
            "session_distribution": []
        }
        
    try:
        # 1. Total unique contracts ingested globally
        unique_contracts = engine.db[config.CHUNKS_COLLECTION].distinct("metadata.contract_id")
        total_contracts = len(unique_contracts)
        
        # 2. Group by session_id and count distinct contract_ids per session
        pipeline = [
            {
                "$group": {
                    "_id": "$metadata.session_id",
                    "contracts": {"$addToSet": "$metadata.contract_id"}
                }
            }
        ]
        aggregation_results = list(engine.db[config.CHUNKS_COLLECTION].aggregate(pipeline))
        
        # 3. Get query distribution and titles from ChatMemory
        query_distribution = []
        session_titles = {}
        if memory:
            try:
                pipeline = [
                    {
                        "$project": {
                            "_id": 1,
                            "title": 1,
                            "updated_at": 1,
                            "query_count": {"$size": "$messages"}
                        }
                    },
                    {
                        "$sort": {"updated_at": -1}
                    }
                ]
                query_results = list(memory.col.aggregate(pipeline))
                for res in query_results:
                    session_id_str = str(res["_id"])
                    title = res.get("title") or session_id_str[:8]
                    session_titles[session_id_str] = title
                    # User sends 1 msg, bot sends 1 msg, so user queries = size // 2
                    q_count = max(0, res.get("query_count", 0) // 2)
                    if q_count > 0 and len(query_distribution) < 10:
                        query_distribution.append({
                            "session_id": session_id_str,
                            "title": title,
                            "query_count": q_count
                        })
            except Exception as e:
                print("Error fetching query distribution:", e)

        session_distribution = []
        for doc in aggregation_results:
            session_id = doc.get("_id")
            # Format None or empty session IDs
            session_id_str = str(session_id) if session_id is not None else "global"
            session_id_str = sanitize_session_id(session_id_str)
            
            contracts_list = doc.get("contracts", [])
            # Filter out None/empty contract IDs if any exist
            valid_contracts = [c for c in contracts_list if c]
            
            session_distribution.append({
                "session_id": session_id_str,
                "title": session_titles.get(session_id_str, "Global Context" if session_id_str == "global" else session_id_str[:8]),
                "contracts_count": len(valid_contracts),
                "contracts": valid_contracts
            })
            
        # Sort session distribution by contracts_count descending
        session_distribution.sort(key=lambda x: x["contracts_count"], reverse=True)
                
        return {
            "total_contracts": total_contracts,
            "session_distribution": session_distribution,
            "query_distribution": query_distribution
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")


@app.post("/api/chat")
def chat(request: ChatRequest):
    if not engine:
        raise HTTPException(status_code=503, detail="Engine still booting. Try again shortly.")

    raw_session_id = request.session_id
    if raw_session_id:
        session_id_clean = sanitize_session_id(raw_session_id)
        session_id_to_search = session_id_clean
    else:
        session_id_clean = str(uuid.uuid4())
        session_id_to_search = None

    # Load history from MongoDB (or empty list if memory is disabled)
    history = memory.get_history(session_id_clean) if memory else []

    try:
        answer, contexts, triplets = engine.answer_query(request.query, chat_history=history, session_id=session_id_to_search)

        # Persist both turns to MongoDB
        if memory:
            # Auto-create the session doc if it doesn't exist yet
            if not memory.has_session(session_id_clean):
                title = request.query[:40] + ("..." if len(request.query) > 40 else "")
                memory.create_session(session_id_clean, title=title)
            memory.append(session_id_clean, "user", request.query)
            memory.append(session_id_clean, "assistant", answer)
            memory.log_activity(session_id_clean, f"Query: '{request.query[:30]}...'", "Info")

        return {
            "answer": answer,
            "contexts": contexts,
            "triplets": triplets,
            "session_id": session_id_clean,
        }
    except Exception as e:
        import traceback
        trace_str = traceback.format_exc()
        print(f"❌ Chat Error: {trace_str}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}\n\nTraceback:\n{trace_str}")


from fastapi.staticfiles import StaticFiles

# ==========================================
# 🌐 FRONTEND
# ==========================================
frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
