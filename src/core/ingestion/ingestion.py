"""
PDF Ingestion Pipeline
=======================
Handles the full lifecycle of a user-uploaded PDF:
  parse → chunk → embed → insert VDB → extract KG → insert KG.
"""

import json
import uuid
import time
from datetime import datetime

from src.core.common import config
from src.core.common.utils import chunk_text, sanitize_session_id
from src.core.ingestion.pdf_parser import extract_text_from_pdf
from src.core.ingestion.kg_builder import upsert_graph_data


def extract_kg_using_llm(llm_manager, text):
    """
    Call LLM to extract structured contract JSON from raw text.

    Returns:
        dict: Extracted contract data, or empty dict on failure.
    """
    system_prompt = (
        "You are a legal AI assistant. Your task is to extract structured entities "
        "and relationships from the provided contract text. "
        "You must return ONLY a raw JSON object matching the requested schema, "
        "with no markdown formatting blocks, no ```json tags, and no explanations."
    )

    user_prompt = (
        "Extract the contract metadata, parties, locations, and clauses "
        "from the following contract text:\n\n"
        f"[START CONTRACT TEXT]\n{text}\n[END CONTRACT TEXT]\n\n"
        "Return a JSON object with this exact structure "
        "(if a field is not found in the text, use null or an empty list):\n"
        "{\n"
        '  "contract_type": "Master Services Agreement / Lease / NDA / etc.",\n'
        '  "effective_date": "YYYY-MM-DD or null",\n'
        '  "contract_scope": "Brief description of scope",\n'
        '  "duration": "Duration of contract",\n'
        '  "end_date": "YYYY-MM-DD or null",\n'
        '  "total_amount": "Total financial value if mentioned, else null",\n'
        '  "summary": "One sentence summary of the contract",\n'
        '  "parties": [\n'
        "    {\n"
        '      "name": "Full legal name of the party",\n'
        '      "role": "Client / Service Provider / etc.",\n'
        '      "location": {\n'
        '        "address": "Street address if mentioned, else null",\n'
        '        "city": "City or null",\n'
        '        "state": "State/Province or null",\n'
        '        "country": "Country name or null"\n'
        "      }\n"
        "    }\n"
        "  ],\n"
        '  "governing_law": {\n'
        '    "address": "Address or null",\n'
        '    "city": "City or null",\n'
        '    "state": "State/Province or null",\n'
        '    "country": "Country name or null"\n'
        "  },\n"
        '  "clauses": [\n'
        "    {\n"
        '      "clause_type": "Term and Termination / Governing Law / '
        'Limitation of Liability / Confidentiality / Indemnification",\n'
        '      "summary": "Concise summary of the clause"\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    try:
        full_prompt = f"SYSTEM INSTRUCTIONS:\n{system_prompt}\n\nUSER REQUEST:\n{user_prompt}"
        resp_text = llm_manager.generate(full_prompt)

        # More robust JSON extraction for Groq/Llama
        start_idx = resp_text.find('{')
        end_idx = resp_text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            resp_text = resp_text[start_idx:end_idx+1]

        return json.loads(resp_text)
    except Exception as e:
        print(f"❌ LLM KG extraction failed: {e}\nResponse was: {resp_text}")
        return {}


def ingest_pdf(db, embedder, llm_manager, filename, pdf_bytes, session_id):
    """
    Full PDF ingestion pipeline: parse → chunk → embed → VDB insert → KG extract.

    Args:
        db: pymongo Database instance.
        embedder: SentenceTransformer model.
        llm_manager: LLMManager instance.
        filename: Original PDF filename.
        pdf_bytes: Raw PDF file contents.
        session_id: Session identifier for isolation.

    Returns:
        dict: Ingestion result with metrics.
    """
    if session_id:
        session_id = sanitize_session_id(session_id)

    total_start = time.time()

    # 1. Parse PDF text
    parse_start = time.time()
    raw_text = extract_text_from_pdf(pdf_bytes)
    parse_time = time.time() - parse_start

    if not raw_text.strip():
        raise ValueError("PDF file is empty or scanned without OCR.")

    # 2. Chunk text (500 words, 100 overlap)
    chunk_start = time.time()
    chunks = chunk_text(raw_text, chunk_size=500, overlap=100)
    chunk_time = time.time() - chunk_start

    # 3. Generate embeddings
    embed_start = time.time()
    embeddings = embedder.encode(
        chunks, normalize_embeddings=True, convert_to_numpy=True
    )
    embed_time = time.time() - embed_start

    # 4. Assemble payloads
    payloads = []
    for idx, text in enumerate(chunks):
        payloads.append({
            "_id": str(uuid.uuid4()),
            "text": text,
            "embedding": embeddings[idx].tolist(),
            "metadata": {
                "contract_id": filename,
                "session_id": session_id,
                "chunk_index": idx,
                "word_count": len(text.split()),
                "ingested_at": datetime.utcnow().isoformat() + "Z",
            },
        })

    # 5. Insert into MongoDB
    db_start = time.time()
    if payloads and db is not None:
        db[config.CHUNKS_COLLECTION].insert_many(payloads)
    else:
        print("⚠️ Warning: MongoDB connection not available. Discarding ingested chunks.")
    db_time = time.time() - db_start

    # 6. Extract and insert Knowledge Graph elements using LLM
    kg_start = time.time()
    kg_extracted = False
    if db is not None:
        try:
            extraction_data = extract_kg_using_llm(llm_manager, raw_text)
            if extraction_data:
                upsert_graph_data(db, filename, extraction_data, session_id)
                kg_extracted = True
        except Exception as e:
            print(f"⚠️ Dynamic KG extraction or insertion failed: {e}")
    kg_time = time.time() - kg_start

    total_time = time.time() - total_start

    return {
        "contract_id": filename,
        "session_id": session_id,
        "chunks_count": len(payloads),
        "kg_extracted": kg_extracted,
        "status": "success",
        "metrics": {
            "parse_time_seconds": round(parse_time, 4),
            "chunk_time_seconds": round(chunk_time, 4),
            "embed_time_seconds": round(embed_time, 4),
            "db_insert_time_seconds": round(db_time, 4),
            "kg_extraction_time_seconds": round(kg_time, 4),
            "total_time_seconds": round(total_time, 4),
        },
    }
