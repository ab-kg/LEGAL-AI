"""
Document routes
================
PDF ingestion plus the read-back views the frontend renders: indexed chunks,
the extracted Knowledge Graph, and structured contract metadata.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from src.core.common import config
from src.core.common.security import get_current_user
from src.api.deps import get_engine, get_memory, require_owned_session

router = APIRouter(prefix="/api/session/{session_id}", tags=["documents"])
NO_DB_NOTE = "MongoDB is not connected. Local fallback mode has no PDF storage."


@router.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_pdf(
    session_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    engine=Depends(get_engine),
    memory=Depends(get_memory),
):
    """Parse, chunk, embed, and graph a contract PDF into a session."""
    session_id = require_owned_session(session_id, user, memory)

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported.")

    try:
        pdf_bytes = await file.read()

        if not memory.has_session(session_id, user_id=user["id"]):
            memory.create_session(
                session_id, title=f"Upload: {file.filename}", user_id=user["id"]
            )
        memory.log_activity(
            session_id, f"Ingested PDF: {file.filename}", "Success", user_id=user["id"]
        )

        result = engine.ingest_pdf(file.filename, pdf_bytes, session_id)

        memory.append(
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

@router.get("/chunks")
def get_session_chunks(
    session_id: str,
    user: dict = Depends(get_current_user),
    engine=Depends(get_engine),
    memory=Depends(get_memory),
):
    """Metadata and text snippets for documents indexed in this session."""
    session_id = require_owned_session(session_id, user, memory)

    if engine.db is None:
        return {
            "session_id": session_id,
            "has_pdf": False,
            "contracts": [],
            "chunks_count": 0,
            "chunks": [],
            "note": NO_DB_NOTE,
        }

    try:
        chunks = list(
            engine.db[config.CHUNKS_COLLECTION].find(
                {"metadata.session_id": session_id},
                {"embedding": 0},
            )
        )

        contracts = {
            doc.get("metadata", {}).get("contract_id", "Unknown")
            for doc in chunks
            if doc.get("metadata")
        }

        formatted = []
        for doc in chunks:
            metadata = doc.get("metadata", {})
            text = doc.get("text", "") or ""
            formatted.append(
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
            "contracts": sorted(contracts),
            "chunks_count": len(chunks),
            "chunks": formatted,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")

@router.get("/graph")
def get_session_graph(
    session_id: str,
    user: dict = Depends(get_current_user),
    engine=Depends(get_engine),
    memory=Depends(get_memory),
):
    """Knowledge Graph nodes and edges extracted for this session."""
    session_id = require_owned_session(session_id, user, memory)

    if engine.db is None:
        return {
            "session_id": session_id,
            "nodes": [],
            "edges": [],
            "note": NO_DB_NOTE,
        }

    try:
        nodes = list(engine.db[config.KG_NODES_COLLECTION].find({"session_id": session_id}))
        edges = list(engine.db[config.KG_EDGES_COLLECTION].find({"session_id": session_id}))

        # ObjectIds are not JSON-serialisable; flatten them to strings.
        formatted_nodes = [{**n, "_id": str(n["_id"])} for n in nodes]
        formatted_edges = [{**e, "_id": str(e["_id"])} if "_id" in e else e for e in edges]

        if formatted_nodes:
            try:
                memory.log_activity(
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

@router.get("/contracts")
def get_session_contracts(
    session_id: str,
    user: dict = Depends(get_current_user),
    engine=Depends(get_engine),
    memory=Depends(get_memory),
):
    """Structured metadata for the contracts indexed in this session."""
    session_id = require_owned_session(session_id, user, memory)

    if engine.db is None:
        return {"session_id": session_id, "contracts": [], "note": NO_DB_NOTE}

    try:
        contracts = engine.db[config.KG_NODES_COLLECTION].find(
            {"entity_type": "Contract", "session_id": session_id}
        )
        formatted = [
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
            "contracts_count": len(formatted),
            "contracts": formatted,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")