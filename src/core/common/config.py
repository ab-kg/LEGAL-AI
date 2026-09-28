"""
Configuration
==============
Credentials, model identifiers, and collection names.
Loaded from environment variables.
"""

import os
from dotenv import load_dotenv

# Load .env locally.
# On Railway, variables are injected directly into the environment.
load_dotenv()


# ─── CREDENTIALS ────────────────────────────────────────────────

raw_key = (
    os.getenv("GROQ_API_KEY", "").strip()
    or os.getenv("GROQ_API_KEYS", "").strip()
)

GROQ_API_KEYS = [k.strip() for k in raw_key.split(",") if k.strip()]
GROQ_API_KEY = GROQ_API_KEYS[0] if GROQ_API_KEYS else ""

MONGO_URI = os.getenv("MONGO_URI", "").strip()

# Database name inside the cluster. Override this to keep a scratch/dev
# database separate from real ingested documents on a shared Atlas cluster.
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "legal_rag").strip()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").strip().lower()


# ─── DATABASE COLLECTIONS ──────────────────────────────────────

CHUNKS_COLLECTION = os.getenv("CHUNKS_COLLECTION", "chunks").strip()
KG_NODES_COLLECTION = os.getenv("KG_NODES_COLLECTION", "kg_nodes").strip()
KG_EDGES_COLLECTION = os.getenv("KG_EDGES_COLLECTION", "kg_edges").strip()
USERS_COLLECTION = os.getenv("USERS_COLLECTION", "users").strip()


# ─── ADMIN CREDENTIALS ─────────────────────────────────────────

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()


# ─── MODELS ────────────────────────────────────────────────────

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

# Model identifiers are env-driven because available models vary per Groq API
# key; run `curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"`
# to list the ones your key can actually reach.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()


# ─── PATHS ─────────────────────────────────────────────────────

GRAPH_PATH = "./legal_kg.json"