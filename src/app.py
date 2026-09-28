"""
Application entry point
=======================
Composition root only: build the FastAPI app, own the startup/shutdown
lifecycle, register middleware and routers, and serve the frontend.

All request handling lives under ``src/api/``, the RAG engine under
``src/core/``, and credentials and hashing under ``src/core/common/``.
"""

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api import admin, auth, chat, documents, overview, sessions
from src.core.common import config
from src.core.common.security import hash_password, validate_username
from src.core.common.utils import force_ipv4
from src.core.rag.chat_memory import ChatMemory

# Resolve IPv4 only before any network I/O; some CI runners and networks have
# broken IPv6 routing that otherwise causes silent timeouts.
force_ipv4()

# Set LEGAL_AI_SKIP_RAG=1 to run the whole app — auth, sessions, the web UI —
# without installing torch/sentence-transformers or booting the embedding model.
# Ingestion and chat return clearly-marked placeholders instead of real answers.
# Intended for UI and auth work only; never enable it in production.
SKIP_RAG = os.getenv("LEGAL_AI_SKIP_RAG", "").strip().lower() in ("1", "true", "yes")

# Explicit allowlist. A wildcard origin combined with credentials is rejected by
# browsers and would let any site on the internet call this API.
ALLOWED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
    ).split(",")
    if origin.strip()
]

class NullEngine:
    """Stands in for LegalGraphRAG when LEGAL_AI_SKIP_RAG is set.
    Exposes just enough of the real interface for the API and frontend to work
    end to end while the embedding model is absent.
    """
    
    def __init__(self, db=None):
        self.db = db

    def ingest_pdf(self, filename, pdf_bytes, session_id):
        return {
            "status": "skipped",
            "detail": "RAG engine disabled (LEGAL_AI_SKIP_RAG=1); nothing was indexed.",
        }
    
    def answer_query(self, query, chat_history=None, session_id=None):
        return (
            "⚠️ The RAG engine is disabled in this environment "
            "(LEGAL_AI_SKIP_RAG=1), so no retrieval was performed. "
            "Unset that variable to enable real answers.",
            [],
            [],
        )

def _build_engine():
    """Instantiate the RAG engine, or the null stand-in when skipped."""
    if SKIP_RAG:
        print("⚠️  LEGAL_AI_SKIP_RAG=1 — UI/auth-only mode, no RAG engine.")
        from src.core.common.db import get_database, get_mongo_client
        return NullEngine(db=get_database(get_mongo_client()))
    print("🚀 Booting LegalGraphRAG engine on startup...")
    # Imported lazily so the heavy ML dependencies are only needed when the
    # RAG engine is actually in use.
    from src.core.rag_pipeline import LegalGraphRAG
    return LegalGraphRAG()

def _seed_admin(db) -> None:
    """Create the admin account on first boot if credentials are configured."""
    if not (config.ADMIN_USERNAME and config.ADMIN_PASSWORD):
        print("⚠️ ADMIN_USERNAME/ADMIN_PASSWORD not set — no admin seeded.")
        return

    users_col = db[config.USERS_COLLECTION]
    admin_name = validate_username(config.ADMIN_USERNAME)

    if users_col.count_documents({"username": admin_name}):
        print(f"👤 Admin user already present: {admin_name}")
        return
    
    users_col.insert_one(
        {
            "_id": str(uuid.uuid4()),
            "username": admin_name,
            "password": hash_password(config.ADMIN_PASSWORD),
            "role": "admin",
        }
    )
    print(f"👤 Created default admin user: {admin_name}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open shared resources once, then tear them down on shutdown.

    Both are attached to ``app.state`` rather than module globals so routers can
    reach them through dependencies and tests can substitute them.
    """
    app.state.engine = _build_engine()
    print("✅ Engine ready — accepting requests.")

    db = getattr(app.state.engine, "db", None)
    if db is None:
        app.state.db = None
        app.state.memory = None
        print("⚠️ No MongoDB — chat memory disabled (sessions are ephemeral).")
    else:
        app.state.db = db
        app.state.memory = ChatMemory(db)
        app.state.memory.ensure_indexes()
        print("💬 Chat memory ready (MongoDB Atlas).")
        _seed_admin(db)
    yield
    print("🛑 Shutting down.")


def create_app() -> FastAPI:
    application = FastAPI(
        title="Legal AI GraphRAG API",
        version="3.0.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @application.middleware("http")
    async def no_cache_frontend_assets(request: Request, call_next):
        """The SPA ships plain HTML/CSS/JS, so never let a stale copy stick."""
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.endswith((".html", ".js", ".css")):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @application.get("/api/health", tags=["ops"])
    def health_check(request: Request):
        """Liveness probe. Deliberately public so the platform can reach it."""
        return {
            "status": "healthy",
            "engine_ready": getattr(request.app.state, "engine", None) is not None,
            "memory_enabled": getattr(request.app.state, "memory", None) is not None,
        }

    for module in (auth, sessions, documents, chat, overview, admin):
        application.include_router(module.router)

    # Mounted last so every API route above takes precedence over the SPA.
    frontend_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "frontend")
    )
    if os.path.exists(frontend_dir):
        application.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn
    # Imported as `src.app` so it resolves from the project root; running this
    # file directly would put src/ on sys.path and break the src.* imports.
    uvicorn.run("src.app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
