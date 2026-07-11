"""
Configuration
==============
Credentials, model identifiers, and collection names.
Loaded from environment variables with sensible defaults.
"""

import os
from dotenv import load_dotenv

# Automatically load environment variables from .env
load_dotenv()

# ─── CREDENTIALS ────────────────────────────────────────────────
raw_key = os.getenv("GROQ_API_KEY", "").strip() or os.getenv("GROQ_API_KEYS", "").strip()
GROQ_API_KEYS = [k.strip() for k in raw_key.split(",") if k.strip()]
if not GROQ_API_KEYS:
    GROQ_API_KEYS = [""]
GROQ_API_KEY = GROQ_API_KEYS[0]

MONGO_URI = os.getenv("MONGO_URI", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()

# ─── DATABASE COLLECTIONS ──────────────────────────────────────
CHUNKS_COLLECTION = os.getenv("CHUNKS_COLLECTION", "chunks")
KG_NODES_COLLECTION = os.getenv("KG_NODES_COLLECTION", "kg_nodes")
KG_EDGES_COLLECTION = os.getenv("KG_EDGES_COLLECTION", "kg_edges")

# ─── MODELS ─────────────────────────────────────────────────────
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
GROQ_MODEL = "llama-3.1-8b-instant"
GEMINI_MODEL = "gemini-2.5-flash"

# ─── PATHS ──────────────────────────────────────────────────────
GRAPH_PATH = "./legal_kg.json"