# Legal AI — API Reference

REST API for the Legal AI GraphRAG backend. This document matches the **`temp`** branch (`src/app.py`).

> **Interactive docs:** With the server running, visit [`/docs`](http://localhost:8000/docs) (Swagger) or [`/redoc`](http://localhost:8000/redoc).

---

## Server

| Item | Value |
|------|--------|
| Local URL | `http://localhost:8000` |
| API base | `http://localhost:8000/api` |
| Frontend | `http://localhost:8000/` (static UI when `frontend/` exists) |
| Health | `GET /api/health` |

**Start (from repo root):**

```bash
python3 -m uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload
```

---

## Endpoint index

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Service health |
| `POST` | `/api/session` | Create session ID (lazy — no DB write until first use) |
| `GET` | `/api/sessions` | List recent sessions |
| `DELETE` | `/api/session/{session_id}` | Delete session |
| `PUT` | `/api/session/{session_id}/rename` | Rename session title |
| `GET` | `/api/session/{session_id}` | Message history + activity log |
| `POST` | `/api/session/{session_id}/ingest` | Upload PDF contract |
| `GET` | `/api/session/{session_id}/chunks` | List ingested chunks |
| `GET` | `/api/session/{session_id}/graph` | Knowledge graph nodes & edges |
| `GET` | `/api/session/{session_id}/contracts` | Contract metadata summaries |
| `GET` | `/api/overview/summary` | Global ingestion & query metrics |
| `POST` | `/api/chat` | Hybrid RAG chat query |

---

## Health

### `GET /api/health`

**Response `200`:**

```json
{
  "status": "healthy",
  "engine_ready": true,
  "memory_enabled": true
}
```

---

## Sessions

### `POST /api/session`

Creates a UUID session ID. Does **not** write to MongoDB until the first chat message or PDF upload.

**Response `200`:**

```json
{
  "session_id": "0dfb6c6b-67a6-4a4a-9351-ccb82b13c7db"
}
```

### `GET /api/sessions`

Returns up to 20 sessions with messages, sorted by `updated_at` descending.

**Response `200`:**

```json
{
  "sessions": [
    {
      "session_id": "0dfb6c6b-67a6-4a4a-9351-ccb82b13c7db",
      "title": "What is the termination clause?",
      "created_at": "2026-06-22T11:25:33+00:00",
      "updated_at": "2026-06-22T11:27:12+00:00"
    }
  ]
}
```

### `GET /api/session/{session_id}`

Returns the last 50 messages and the session activity log.

**Response `200`:**

```json
{
  "session_id": "0dfb6c6b-67a6-4a4a-9351-ccb82b13c7db",
  "messages": [
    { "role": "user", "content": "What is the termination clause?" },
    { "role": "assistant", "content": "Either party may terminate with 60 days notice..." }
  ],
  "activity": [
    {
      "title": "Session initialized",
      "status": "Info",
      "timestamp": "2026-06-22T11:25:33+00:00"
    },
    {
      "title": "Query: 'What is the termination...'",
      "status": "Info",
      "timestamp": "2026-06-22T11:27:12+00:00"
    }
  ]
}
```

### `PUT /api/session/{session_id}/rename`

**Request body:**

```json
{
  "title": "MSA review — Acme contract"
}
```

**Response `200`:**

```json
{
  "status": "renamed",
  "session_id": "0dfb6c6b-67a6-4a4a-9351-ccb82b13c7db",
  "title": "MSA review — Acme contract"
}
```

### `DELETE /api/session/{session_id}`

Deletes the session document from MongoDB.

**Response `200`:**

```json
{
  "status": "deleted",
  "session_id": "0dfb6c6b-67a6-4a4a-9351-ccb82b13c7db"
}
```

---

## PDF ingestion

### `POST /api/session/{session_id}/ingest`

Upload a legal contract PDF for session-scoped retrieval.

**Request:** `multipart/form-data` with field `file` (PDF only).

**Response `201`:**

```json
{
  "status": "success",
  "contract_id": "sample_legal_contract.pdf",
  "session_id": "0dfb6c6b-67a6-4a4a-9351-ccb82b13c7db",
  "chunks_count": 8,
  "kg_extracted": true,
  "metrics": {
    "parse_time": 0.12,
    "embed_time": 1.4,
    "db_time": 0.3,
    "kg_time": 2.1
  }
}
```

**Errors:** `400` if not a PDF; `503` if engine not ready; `500` on ingestion failure.

---

## Inspection

### `GET /api/session/{session_id}/chunks`

**Response `200`:**

```json
{
  "session_id": "0dfb6c6b-67a6-4a4a-9351-ccb82b13c7db",
  "has_pdf": true,
  "contracts": ["sample_legal_contract.pdf"],
  "chunks_count": 2,
  "chunks": [
    {
      "chunk_id": "64bc1dfa14e9f1",
      "contract_id": "sample_legal_contract.pdf",
      "chunk_index": 0,
      "word_count": 320,
      "text_snippet": "This Master Services Agreement is entered into..."
    }
  ]
}
```

### `GET /api/session/{session_id}/graph`
Returns KG nodes and edges extracted for this session.
**Response `200`:**
```json
{
  "session_id": "0dfb6c6b-67a6-4a4a-9351-ccb82b13c7db",
  "nodes_count": 4,
  "edges_count": 3,
  "nodes": [
    {
      "_id": "Acme Global Technologies LLC",
      "entity_type": "Party",
      "session_id": "0dfb6c6b-67a6-4a4a-9351-ccb82b13c7db"
    }
  ],
  "edges": [
    {
      "_id": "edge_123",
      "source": "Acme Global Technologies LLC",
      "target": "Singapore",
      "label": "HAS_GOVERNING_LAW",
      "session_id": "0dfb6c6b-67a6-4a4a-9351-ccb82b13c7db"
    }
  ]
}
```

### `GET /api/session/{session_id}/contracts`

Structured contract metadata from KG `Contract` nodes.

**Response `200`:**

```json
{
  "session_id": "0dfb6c6b-67a6-4a4a-9351-ccb82b13c7db",
  "contracts_count": 1,
  "contracts": [
    {
      "contract_id": "sample_legal_contract.pdf",
      "summary": "Master services agreement between Acme and Apex...",
      "contract_type": "Master Services Agreement",
      "effective_date": "2026-06-10",
      "contract_scope": null,
      "duration": "1 year",
      "end_date": null,
      "total_amount": null
    }
  ]
}
```

### `GET /api/overview/summary`

Global metrics for the overview dashboard.

**Response `200`:**

```json
{
  "total_contracts": 42,
  "session_distribution": [
    {
      "session_id": "0dfb6c6b-67a6-4a4a-9351-ccb82b13c7db",
      "contracts_count": 3,
      "contracts": [
        "sample_legal_contract.pdf",
        "sample_distribution_agreement.pdf",
        "sample_software_license_agreement.pdf"
      ]
    }
  ],
  "query_distribution": [
    {
      "session_id": "0dfb6c6b-67a6-4a4a-9351-ccb82b13c7db",
      "title": "Summarize the contracts",
      "query_count": 5
    }
  ]
}
```

---

## Chat

### `POST /api/chat`

Runs hybrid vector + knowledge-graph retrieval, then generates a grounded answer.

**Request body:**

```json
{
  "query": "What is the termination notice period?",
  "session_id": "0dfb6c6b-67a6-4a4a-9351-ccb82b13c7db"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | yes | Natural language question |
| `session_id` | string | no | Scope retrieval to uploaded PDFs; auto-generated if omitted |

**Behavior:**
- Loads chat history from MongoDB for follow-up condensation.
- If `session_id` has uploaded chunks, searches session documents first; otherwise falls back to the global CUAD corpus.
- Auto-creates session on first message with title from query prefix.
- Persists user + assistant turns and logs activity.

**Response `200`:**

```json
{
  "answer": "Either party may terminate without cause upon sixty (60) days prior written notice.",
  "contexts": [
    "Either Party may terminate this Agreement without cause upon giving at least sixty (60) days..."
  ],
  "triplets": [
    "Acme Global Technologies LLC (Party) --PARTY_TO--> sample_legal_contract.pdf (Contract)"
  ],
  "session_id": "0dfb6c6b-67a6-4a4a-9351-ccb82b13c7db"
}
```

**Errors:** `503` engine booting; `500` on pipeline failure.

---

## Example client (JavaScript)

```javascript
const API = `${window.location.origin}/api`;

async function createSession() {
  const res = await fetch(`${API}/session`, { method: 'POST' });
  return (await res.json()).session_id;
}

async function uploadPdf(sessionId, file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API}/session/${sessionId}/ingest`, {
    method: 'POST',
    body: form,
  });
  return res.json();
}

async function chat(sessionId, query) {
  const res = await fetch(`${API}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, query }),
  });
  return res.json();
}
```

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MONGO_URI` | Yes | MongoDB Atlas connection string |
| `GROQ_API_KEY` | If `LLM_PROVIDER=groq` | Groq API key(s), comma-separated |
| `GEMINI_API_KEY` | If `LLM_PROVIDER=gemini` | Google Gemini API key |
| `LLM_PROVIDER` | No | `groq` or `gemini` (default: `gemini`) |
| `PORT` | No | Server port (default `8000`) |

---

## Branch note

This file documents the **`temp`** branch (frontend UI, session rename/delete, activity log, `query_distribution`). The **`main`** branch API is documented in the same path on that branch — fewer session endpoints and no bundled frontend.
