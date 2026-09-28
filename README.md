# LegalAI — Hybrid GraphRAG Contract Intelligence

A full-stack web application for analysing legal contracts. **Upload a PDF, then
ask questions about it** and get answers grounded in the actual document text and
an auto-extracted Knowledge Graph.

Two retrieval strategies run on every query — dense vector search over embedded
chunks and structured knowledge-graph traversal — and the results are fused into
a single grounded prompt so the model answers from evidence instead of guessing.

> **Stack:** React (vanilla JS) · FastAPI · LangChain-free RAG pipeline · MongoDB
> Atlas (vector search + graph collections) · Groq · PyTorch / Sentence Transformers

---

## What it does

| Capability | Detail |
| :--- | :--- |
| **PDF ingestion** | Parse → chunk (500 words, 100 overlap) → embed → vector store → LLM knowledge-graph extraction |
| **Hybrid retrieval** | Atlas `$vectorSearch` + KG triple expansion, merged into one context window |
| **Conversational QA** | Follow-up questions are rewritten into standalone search queries before retrieval |
| **Multi-user** | Self-registration, JWT sessions, and strict per-user data isolation |
| **Graph visualisation** | Extracted entities and relationships rendered per session |
| **Dashboard** | Per-user contract counts, session distribution, and activity feed |

A worked example — ingesting `sample_software_license_agreement.pdf` and asking
*"What is the governing law?"* produces 11 graph nodes / 10 edges and:

```
The governing law of the agreement is the laws of the United Kingdom,
specifically London.
```

Extracted relationships:

```
(Contract) --HAS_GOVERNING_LAW--> Location_United Kingdom_London
Vertex Analytics Ltd. (Party) --PARTY_TO--> (Contract)
Pacific Retail Systems Pty Ltd (Party) --PARTY_TO--> (Contract)
(Contract) --HAS_CLAUSE--> Clause_..._Term (Clause)
```

When the evidence genuinely does not contain an answer, the model says so rather
than inventing one — the system prompt is explicitly *"answer using ONLY the
provided context... do not hallucinate."*

---

## Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│  Browser — frontend/                                         │
│  login.html · index.html · js/{login,app}.js · styles/       │
│  apiFetch() attaches the bearer token, 401 → re-login        │
└───────────────────────────┬──────────────────────────────────┘
                            │  same origin (FastAPI serves the SPA)
┌───────────────────────────▼──────────────────────────────────┐
│  src/app.py — composition root                               │
│  lifespan · CORS · no-cache · /api/health · static mount     │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  src/api/ — routers (domain-grouped)                         │
│  deps · auth · sessions · documents · chat · overview · admin│
│  every route declares Depends(get_current_user)              │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  src/core/rag_pipeline.py — LegalGraphRAG                    │
│  condense query → vector search → KG match → synthesise → LLM│
└───────┬───────────────────────────────────┬──────────────────┘
        │                                   │
┌───────▼──────────────┐          ┌─────────▼──────────────────┐
│ MongoDB Atlas        │          │ Groq / Gemini               │
│ · chunks  (+ vectors)│          │ openai/gpt-oss-20b         │
│ · kg_nodes / kg_edges│          │ gemini-2.5-flash           │
│ · chat_sessions      │          └────────────────────────────┘
│ · users              │
└──────────────────────┘
```

---

## Directory structure

```text
LEGAL-AI/
├── src/
│   ├── app.py                       # composition root: lifespan, middleware, routers
│   ├── main.py                      # CLI entrypoint (interactive query loop)
│   ├── api/
│   │   ├── deps.py                  # get_db / get_engine / get_memory / ownership
│   │   ├── auth.py                  # register · login · me
│   │   ├── sessions.py              # session CRUD + cascading delete
│   │   ├── documents.py             # ingest · chunks · graph · contracts
│   │   ├── chat.py                  # the conversational turn
│   │   ├── overview.py              # activity feed + dashboard metrics
│   │   └── admin.py                 # admin-only user listing
│   └── core/
│       ├── common/
│       │   ├── config.py            # env vars, collection names, model ids
│       │   ├── db.py                # Mongo client factory
│       │   ├── security.py          # bcrypt hashing, JWT, get_current_user
│       │   └── utils.py             # IPv4 patch, chunking, id sanitisation
│       ├── rag/
│       │   ├── chat_memory.py       # session store, user_id scoping
│       │   ├── llm.py               # LLMManager (Groq / Gemini)
│       │   ├── retrieval.py         # vector search + KG matching
│       │   └── tfidf.py             # lexical retriever
│       ├── ingestion/
│       │   ├── ingestion.py         # PDF → chunks → embeddings → KG
│       │   ├── kg_builder.py        # upsert nodes/edges
│       │   └── pdf_parser.py
│       └── rag_pipeline.py          # LegalGraphRAG orchestrator
├── frontend/                        # vanilla JS SPA served by FastAPI
├── tests/
│   ├── security/test_auth_isolation.py
│   ├── e2e/ · benchmarks/
├── tools/
│   ├── smoke_live.py                # auth flow against a running server
│   └── smoke_rag.py                 # full RAG: upload a PDF, ask a question
├── Dockerfile                       # multi-stage build
├── requirements.txt
└── README.md
```

---

## API

| Method | Path | Auth | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/register` | — | Create an account, returns a token |
| `POST` | `/api/login` | — | Sign in, returns a JWT |
| `GET` | `/api/me` | ✔ | Current caller's identity |
| `POST` | `/api/session` | ✔ | Create a session (owned by the caller) |
| `GET` | `/api/sessions` | ✔ | List the caller's sessions |
| `GET` | `/api/session/{id}` | ✔ | Message history |
| `PUT` | `/api/session/{id}/rename` | ✔ | Rename |
| `DELETE` | `/api/session/{id}` | ✔ | Delete session + all indexed data |
| `POST` | `/api/session/{id}/ingest` | ✔ | **Upload a contract PDF** |
| `GET` | `/api/session/{id}/chunks` | ✔ | Indexed chunks |
| `GET` | `/api/session/{id}/graph` | ✔ | Knowledge Graph nodes + edges |
| `GET` | `/api/session/{id}/contracts` | ✔ | Structured contract metadata |
| `POST` | `/api/chat` | ✔ | **Ask a question** (RAG) |
| `GET` | `/api/overview/summary` | ✔ | Per-user metrics |
| `GET` | `/api/activity` | ✔ | Per-user activity feed |
| `GET` | `/api/admin/users` | admin | All accounts (passwords excluded) |
| `GET` | `/api/health` | — | Liveness probe |

Only `register`, `login`, and `health` are public.

---

## Setup

### 1. Environment

Create `.env` in the project root:

```env
MONGO_URI=mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/?retryWrites=true&w=majority
GROQ_API_KEY=gsk_...
JWT_SECRET=<32+ random bytes, hex encoded>
GROQ_MODEL=openai/gpt-oss-20b
LLM_PROVIDER=groq
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<strong password>
```

| Variable | Required | Default | Notes |
| :--- | :--- | :--- | :--- |
| `MONGO_URI` | ✔ | — | MongoDB Atlas connection string |
| `GROQ_API_KEY` | ✔ | — | Comma-separated list enables key rotation |
| `JWT_SECRET` | ✔ | random per-process | **Always set it.** Without it, tokens die on every restart |
| `GROQ_MODEL` | | `openai/gpt-oss-20b` | Must exist on your key — list with `GET /v1/models` |
| `GEMINI_API_KEY` | | — | Optional KG-extraction fallback |
| `LLM_PROVIDER` | | `groq` | `groq` or `gemini` |
| `MONGO_DB_NAME` | | `legal_rag` | Override to keep dev data separate |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | | — | Seeds the admin on first boot |
| `ACCESS_TOKEN_HOURS` | | `24` | Token lifetime |
| `CORS_ORIGINS` | | localhost | Unnecessary — the SPA is same-origin |
| `LEGAL_AI_SKIP_RAG` | | unset | `1` runs UI/auth only, no torch needed |

### 2. Install and run

```bash
pip install -r requirements.txt
python -X utf8 -m uvicorn src.app:app --reload --port 8000
```

Open <http://localhost:8000>, register an account, upload a PDF, and ask a question.

> **Windows:** use `python -X utf8` (or set `PYTHONIOENCODING=utf-8`). The console
> defaults to cp1252, which cannot encode the startup log's emoji and raises
> `UnicodeEncodeError`. Do **not** put `PYTHONIOENCODING` in `.env`; it is read at
> interpreter startup, before `.env` is loaded.

### 3. Fast iteration without the ML stack

```bash
pip install fastapi "uvicorn[standard]" python-multipart python-dotenv pydantic \
            bcrypt PyJWT "pymongo[srv]" certifi mongomock

set LEGAL_AI_SKIP_RAG=1     # PowerShell
uvicorn src.app:app --reload --port 8000
```

Auth, sessions, and the whole UI work; chat and ingest return clearly-marked
placeholders instead of real answers. No torch, no sentence-transformers.

---

## Authentication & isolation

- Passwords hashed with **bcrypt**; the 72-byte truncation limit is rejected
  rather than silently ignored.
- **JWT** (HS256) carries `sub`, `role`, `iat`, `exp`.
- Sign-in failures return an identical message for unknown-user and
  wrong-password, so the endpoint cannot be used to enumerate accounts.
- Sessions are persisted **with their owner at creation time**. Ownership is
  then strict, so a client-supplied `session_id` can never be adopted by whoever
  sends it first.
- Cross-user access returns **404, not 403** — a 403 would confirm the session
  exists and turn the endpoint into an ID oracle.
- Activity feeds and dashboard metrics are filtered to the caller.
- Deleting a session cascades to its chunks, KG nodes, and KG edges.

---

## Design notes

**Hybrid retrieval, not just vectors.** Pure vector search misses relational
questions ("who are the parties and where are they located?"). The KG expansion
surfaces entity relationships that don't share vocabulary with the query, and
both are fused before generation.

**Session-scoped retrieval bypasses the Atlas vector index.** When a session is
active, chunks are fetched and scored in-process with a dot product rather than
going through `$vectorSearch`. Atlas indexes are eventually consistent, so a
just-uploaded PDF would be invisible to its own session for a few seconds. The
global `$vectorSearch` path still serves the seed corpus (chunks with no
`session_id`).

**Query condensation.** "What about termination?" retrieves nothing useful on
its own, so follow-ups are rewritten into standalone queries with the contract
name injected before embedding — visible in the logs as
`🔄 Condensed Query: ... ➔ ...`.

**Token budgeting.** VDB chunks are truncated to 800 chars, KG edges capped at 20,
node IDs at 50 — this keeps prompts inside the Groq context window.

**Graceful degradation.** If Atlas is unreachable the engine falls back to a
local NetworkX graph so the API still answers.

---

## Testing

```bash
# 55 auth / isolation tests, no external services needed
pytest tests/security/test_auth_isolation.py

# End-to-end against a running server
python -X utf8 tools/smoke_live.py    # signup → signin → sessions → isolation
python -X utf8 tools/smoke_rag.py     # upload a real PDF → ask a real question
```

The isolation suite covers anonymous access to all 14 protected routes, tampered
tokens, cross-user read/delete/hijack attempts, per-user scoping of the activity
and dashboard feeds, and admin RBAC.

CI (`.github/workflows/ci.yml`) additionally runs the RAG pipeline, chat-memory,
and benchmark suites, which require live Atlas credentials.

---

## Deployment (Railway)

Single container: the Dockerfile builds the frontend with Node and serves it
from FastAPI, so the browser talks to one origin.

```bash
docker build -t legalai .
```

The app listens on **8080** (`${PORT:-8080}`). Point the Railway service's
public domain target port at `8080` — a mismatch returns 502.

Required service variables: `MONGO_URI`, `GROQ_API_KEY`, `JWT_SECRET`,
`ADMIN_USERNAME`, `ADMIN_PASSWORD`.

> Railway **stages** variable changes. They do not apply until you deploy the
> staged change.

---

---

## Technology

MongoDB Atlas Vector Search · Groq (`openai/gpt-oss-20b`) · Gemini
(`gemini-2.5-flash`) · `BAAI/bge-small-en-v1.5` (384-dim embeddings) · NetworkX ·
FastAPI · PyTorch · Sentence Transformers · Railway · GitHub Actions
