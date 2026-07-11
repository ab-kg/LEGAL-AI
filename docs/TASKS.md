# Task List

## Open

- [ ] **Persist context & graph in chat history** — Retrieved Context and Graph Relationships disappear when switching sessions. Backend only saves `content` (`chat_memory.py`, `app.py`); frontend `loadSession()` replays text only (`app.js`). Store `contexts` + `triplets` on assistant messages; render on reload.

## Done

## Later

- Session-only retrieval (no global fallback)
- “Summarize session” intent routing
- Corpus scope indicator in UI
