# 🏛️ Legal AI GraphRAG Pipeline

A **Hybrid GraphRAG (Graph-Augmented Retrieval-QA) API** for deep legal contract understanding. It combines **Dense Semantic Retrieval** (MongoDB Atlas Vector Search) with a **Structured Knowledge Graph** (MongoDB Atlas collections) to provide grounded, hallucination-resistant answers via a **Groq LLM**. Deployed as a backend-only FastAPI service on **Railway**.

---


---

## 📂 Directory Structure

```text
legal-ai-kg/
├── src/
│   └── core/                              # Core pipeline & logic engine
│       ├── __init__.py                    # Package init — exposes LegalGraphRAG, build_infrastructure
│       ├── config.py                      # Models, API keys, collection names
│       ├── utils.py                       # Shared helpers (IPv4 patch, safe_str, chunking)
│       ├── db.py                          # MongoDB connection factory
│       ├── llm.py                         # Dual-provider LLM manager (Gemini/Groq)
│       ├── retrieval.py                   # Vector search + KG matching
│       ├── ingestion.py                   # PDF ingestion pipeline
│       ├── kg_builder.py                  # Builds KG from contract_data.json
│       ├── data_loader.py                 # CUAD dataset ingestion
│       └── rag_pipeline.py                # Orchestrator: delegates to db, llm, retrieval, ingestion
├── scripts/
│   └── index_to_mongodb.py               # Bulk VDB indexer: chunks CUAD contracts → MongoDB Atlas
├── tests/
│   ├── conftest.py                        # Shared test fixtures
│   ├── test_rag_pipeline.py               # 3-question end-to-end RAG test (used in CI)
│   ├── test_chat_memory.py                # Persistent Chat Memory E2E test (used in CI)
│   ├── test_standalone_100.py             # 100 standalone queries evaluation benchmark (used in CI)
│   ├── test_followups_25.py               # 25 multi-turn scenarios evaluation benchmark (used in CI)
│   └── test_api_integration.py            # FastAPI server integration test
├── data/
│   └── CUADv1.json                        # CUAD dataset (40MB, local copy)
├── research/
│   └── import-graph/
│       └── contract_data.json             # 510 structured contract records for KG construction
├── reports/                               # Generated test/benchmark reports
├── .github/
│   └── workflows/
│       └── ci.yml                         # GitHub Actions CI — manual trigger only (workflow_dispatch)
├── app.py                                 # FastAPI backend: lifespan boot, /api/health, /api/session, /api/chat
├── main.py                                # CLI entrypoint (build + interactive query loop)
├── Procfile                               # Process definition for Railway
├── railway.toml                           # Railway deployment config (Nixpacks, health check, restart policy)
├── .railwayignore                         # Files excluded from Railway builds
├── requirements.txt                       # Production dependencies (lean, for Railway)
├── requirements-dev.txt                   # Development dependencies (includes pandas, tqdm for benchmarks)
├── .gitignore
├── CONTEXT.md                             # Living context document for AI assistants
└── README.md                              # This file
```

---

## 📋 Core Module Reference

| Module | Description | Key Exports |
| :--- | :--- | :--- |
| **`src/core/config.py`** | API keys (via env), model names, file paths, collection names. | `EMBEDDING_MODEL`, `GEMINI_MODEL`, `GROQ_MODEL`, `MONGO_URI` |
| **`src/core/utils.py`** | Shared utilities for the project. | `force_ipv4`, `safe_str`, `make_location_id`, `chunk_text` |
| **`src/core/db.py`** | MongoDB connection management. | `get_mongo_client`, `get_database`, `ping` |
| **`src/core/llm.py`** | Dual-provider LLM manager (Gemini/Groq). | `LLMManager` |
| **`src/core/retrieval.py`** | Vector search and Knowledge Graph matching. | `vector_search`, `graph_match_mongo`, `synthesize_context` |
| **`src/core/ingestion.py`** | PDF ingestion and dynamic KG extraction pipeline. | `ingest_pdf`, `extract_kg_using_gemini` |
| **`src/core/kg_builder.py`** | Builds NetworkX graph, uploads nodes/edges to MongoDB Atlas. | `build_infrastructure`, `build_graph_elements`, `upsert_graph_data` |
| **`src/core/rag_pipeline.py`** | Orchestrator for RAG pipeline. | `LegalGraphRAG` |
| **`app.py`** | FastAPI backend with lifespan auto-boot, session management, and chat endpoint. | `health_check`, `chat`, `create_session` |
| **`main.py`** | CLI orchestrator: builds infrastructure, starts interactive query loop. | `main` |

---

## 📦 Setup & Installation

### Environment Variables

Create a `.env` file in the project root with:
```env
MONGO_URI=mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/?retryWrites=true&w=majority
# Can be a single key or a comma-separated list of keys for API key rotation
GROQ_API_KEY=gsk_key1,gsk_key2
```

### Dependencies

To support both lightweight cloud deployments and local development, dependencies are split:

* **Production Deployment** (minimal footprint, for Railway / cloud containers):
  ```bash
  pip install -r requirements.txt
  ```

* **Local Development & Benchmarking** (adds `pandas`, `tqdm`, etc.):
  ```bash
  pip install -r requirements-dev.txt
  ```

---

## 🛠️ Execution Guide

### 1. API Server (Production — Railway or Local)

```bash
python src/app.py
```

* The RAG engine boots automatically on startup (downloads embedding model, connects to MongoDB Atlas).
* **Full API reference:** [`docs/api_documentation.md`](docs/api_documentation.md)
* **Task backlog:** [`docs/TASKS.md`](docs/TASKS.md)
* **Interactive Docs**: Visit `http://localhost:8000/docs` for Swagger UI.
* **Frontend UI** (this branch): Visit `http://localhost:8000/` after starting the server.

**Endpoints (summary):**

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Health check |
| `POST` | `/api/session` | Create session ID (lazy DB write) |
| `GET` | `/api/sessions` | List recent sessions |
| `DELETE` | `/api/session/{session_id}` | Delete session |
| `PUT` | `/api/session/{session_id}/rename` | Rename session |
| `GET` | `/api/session/{session_id}` | Messages + activity log |
| `POST` | `/api/session/{session_id}/ingest` | Upload PDF |
| `GET` | `/api/session/{session_id}/chunks` | View chunks |
| `GET` | `/api/session/{session_id}/graph` | View knowledge graph |
| `GET` | `/api/session/{session_id}/contracts` | Contract summaries |
| `GET` | `/api/overview/summary` | Global metrics |
| `POST` | `/api/chat` | RAG chat query |

### 2. Command Line Interface (CLI)

```bash
python src/main.py
```

* Runs KG indexing, then starts an interactive query prompt loop.

### 3. One-Time Indexing Scripts

These only need to be run once to populate MongoDB Atlas:

```bash
# Index CUAD contracts into the Vector DB (chunks collection)
python src/scripts/index_to_mongodb.py

# Index structured KG data into kg_nodes / kg_edges collections
python -m src.core.kg_builder
```

---

## 🚀 Railway Deployment

The project is configured for one-click Railway deployment:

1. **Connect** your GitHub repo to Railway and select the `railway` branch.
2. **Set environment variables** in Railway dashboard: `MONGO_URI` and `GROQ_API_KEY`.
3. Railway auto-builds with Nixpacks, runs `uvicorn src.app:app`, and health-checks via `/api/health`.
4. Config is in `railway.toml` (300s health check timeout to allow embedding model download on cold start).

---

## 🔄 CI/CD

GitHub Actions workflow (`.github/workflows/ci.yml`) triggers on pushes to the `feature/chat-memory`, `main`, and `feat/evidence-logging` branches, as well as manually via `workflow_dispatch`.

The pipeline executes the following checks:
1. **RAG Pipeline Test** (`tests/e2e/test_rag_pipeline.py`) — runs 3 baseline query evaluations.
2. **Chat Memory E2E Test** (`tests/e2e/test_chat_memory.py`) — runs multi-session isolation and history truncation tests.
3. **Standalone 100 Benchmark** (`tests/benchmarks/test_standalone_100.py`) — runs 100 standalone queries with API key rotation, incremental report saving, and a graceful 40-minute timeout.
4. **Followups 25 Benchmark** (`tests/benchmarks/test_followups_25.py`) — runs 25 multi-turn scenarios under the same key rotation and timeout guards.

Reports for all test suites are uploaded as GitHub Action run artifacts.

---

## 💎 Design Highlights

1. **Hybrid Retrieval**: Combines dense vector search (semantic similarity) with structured KG triples (entity relationships) for comprehensive context.
2. **Token-Efficient Context**: VDB chunks capped at 800 chars, KG edges limited to 20, node IDs truncated to 50 chars — prevents Groq token limit errors.
3. **Read-Only Production**: The deployed API and CI pipeline never write to MongoDB Atlas — all indexing is done offline via scripts.
4. **Graceful Fallback**: If MongoDB Atlas is unreachable, the engine falls back to a local `legal_kg.json` NetworkX graph.

---

## 🛠️ Technology Stack

* **MongoDB Atlas Vector Search** — Cloud-hosted vector database for semantic similarity search.
* **Groq (Llama 3.1 8B Instant)** — High-speed LLM for answer generation.
* **BAAI/bge-small-en-v1.5** — Sentence embedding model (384-dimensional vectors).
* **NetworkX** — In-memory graph library used during KG construction.
* **FastAPI** — Python web framework powering the REST API.
* **Sentence Transformers** — PyTorch-based dense vector embedding framework.
* **Railway** — Cloud platform for deployment.
* **GitHub Actions** — CI pipeline for automated testing.
