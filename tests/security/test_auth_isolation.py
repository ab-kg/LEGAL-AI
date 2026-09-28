"""Auth + multi-tenancy tests for LEGAL-AI.

The RAG stack (torch, sentence-transformers) is stubbed out so these run in
seconds on a machine with no MongoDB. What is exercised is the real
`src.app` FastAPI application, the real `security` module, and the real
`ChatMemory` against mongomock.
"""

import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import mongomock
import pytest

# ─── Stub the heavy RAG imports before src.app loads ──────────────────
for mod in [
    "src.core.rag_pipeline",
    "src.core.rag.llm",
    "src.core.rag.tfidf",
    "src.core.rag.retrieval",
    "src.core.ingestion.kg_builder",
    "src.core.ingestion.pdf_parser",
    "src.core.ingestion.ingestion",
    "src.core.ingestion.data_loader",
    "src.core.common.db",
]:
    sys.modules.setdefault(mod, MagicMock())

sys.path.insert(0, r"C:\Users\harsh\Desktop\AB-KG\PROJECTS\LEGAL-AI")

from src.core.common import config  # noqa: E402
from src.core.common import security  # noqa: E402
from src.core.rag.chat_memory import ChatMemory  # noqa: E402
from src import app as app_module  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


# ─── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def env(monkeypatch):
    """A ready-to-use app with mongomock wired in as MongoDB."""
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-a-real-one")
    monkeypatch.setenv("ADMIN_USERNAME", "")
    monkeypatch.setenv("ADMIN_PASSWORD", "")

    # security reads JWT_SECRET at import time
    monkeypatch.setattr(security, "JWT_SECRET", "test-secret-not-a-real-one")

    client_mongo = mongomock.MongoClient()
    db = client_mongo["legal_rag"]

    # Resources now live on app.state rather than module globals, so the
    # routers resolve them through dependencies.
    app_module.app.state.engine = MagicMock()
    app_module.app.state.engine.db = db
    # answer_query must return a real 3-tuple; a bare MagicMock cannot be
    # unpacked, and every chat test would then fail for the wrong reason.
    app_module.app.state.engine.answer_query.return_value = (
        "Mock answer.",
        ["Mock context excerpt."],
        [("Entity", "relation", "Entity")],
    )
    app_module.app.state.engine.ingest_pdf.return_value = {"status": "indexed"}

    app_module.app.state.db = db
    app_module.app.state.memory = ChatMemory(db)
    app_module.app.state.memory.ensure_indexes()

    return TestClient(app_module.app), db


def register(client, username, password="correct-horse"):
    r = client.post("/api/register", json={"username": username, "password": password})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ─── Password + token primitives ──────────────────────────────────────

def test_password_hashing_roundtrip():
    h = security.hash_password("hunter2")
    assert h != "hunter2"
    assert security.verify_password("hunter2", h)
    assert not security.verify_password("hunter3", h)
    assert not security.verify_password("hunter2", "garbage")


def test_password_length_limits():
    with pytest.raises(Exception):
        security.validate_password("short")           # < 8
    security.validate_password("long-enough")          # fine


def test_username_normalisation_and_rules():
    assert security.validate_username("  Alice  ") == "alice"
    for bad in ["ab", "a" * 40, "has space", "bad!char"]:
        with pytest.raises(Exception):
            security.validate_username(bad)


def test_token_roundtrip_and_tamper_detection():
    token = security.create_access_token("alice", "user")
    assert security.decode_token(token)["sub"] == "alice"

    with pytest.raises(Exception):
        security.decode_token(token[:-4] + "AAAA")   # tampered signature

    # a token signed with a different key must not verify
    import jwt as pyjwt
    forged = pyjwt.encode({"sub": "attacker"}, "different-key", algorithm="HS256")
    with pytest.raises(Exception):
        security.decode_token(forged)


def test_expired_token_rejected():
    now = datetime.now(timezone.utc)
    expired = pyjwt_encode_expired(now)
    with pytest.raises(Exception):
        security.decode_token(expired)


def pyjwt_encode_expired(now):
    import jwt as pyjwt

    return pyjwt.encode(
        {"sub": "alice", "exp": now - timedelta(hours=1)}, security.JWT_SECRET, algorithm="HS256"
    )


# ─── The endpoints that must stay public ──────────────────────────────

def test_health_is_public(env):
    client, _ = env
    r = client.get("/api/health")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "healthy"


def test_register_and_login_are_public(env):
    client, _ = env
    assert client.post("/api/register", json={"username": "alice", "password": "correct-horse"}).status_code == 201
    assert client.post("/api/login", json={"username": "alice", "password": "correct-horse"}).status_code == 200


# ─── Every other endpoint must demand a token ─────────────────────────

PROTECTED = [
    ("get", "/api/me", None),
    ("post", "/api/session", None),
    ("get", "/api/sessions", None),
    ("get", "/api/activity", None),
    ("get", "/api/activity/global", None),
    ("get", "/api/overview/summary", None),
    ("post", "/api/chat", {"query": "hi"}),
    ("get", "/api/session/some-id", None),
    ("delete", "/api/session/some-id", None),
    ("put", "/api/session/some-id/rename", {"title": "x"}),
    ("get", "/api/session/some-id/chunks", None),
    ("get", "/api/session/some-id/graph", None),
    ("get", "/api/session/some-id/contracts", None),
    ("get", "/api/admin/users", None),
]


@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_protected_endpoints_reject_anonymous(env, method, path, body):
    client, _ = env
    r = client.request(method, path, json=body)
    assert r.status_code == 401, f"{method.upper()} {path} returned {r.status_code}, expected 401"


@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_protected_endpoints_reject_garbage_token(env, method, path, body):
    client, _ = env
    r = client.request(method, path, json=body, headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401, f"{method.upper()} {path} returned {r.status_code}, expected 401"


# ─── Registration behaviour ───────────────────────────────────────────

def test_duplicate_username_rejected(env):
    client, _ = env
    register(client, "alice")
    r = client.post("/api/register", json={"username": "ALICE", "password": "correct-horse"})
    assert r.status_code == 409, r.text


def test_weak_password_rejected(env):
    client, _ = env
    r = client.post("/api/register", json={"username": "bob", "password": "short"})
    assert r.status_code == 422, r.text


def test_login_failures_are_indistinguishable(env):
    client, _ = env
    register(client, "alice")
    unknown = client.post("/api/login", json={"username": "nobody", "password": "whatever"})
    wrong = client.post("/api/login", json={"username": "alice", "password": "wrong-pass"})
    assert unknown.status_code == 401
    assert wrong.status_code == 401
    # identical detail prevents account enumeration
    assert unknown.json()["detail"] == wrong.json()["detail"]


# ─── Per-user isolation ───────────────────────────────────────────────

def test_me_returns_identity(env):
    client, _ = env
    auth = register(client, "alice")
    r = client.get("/api/me", headers=auth)
    assert r.status_code == 200
    assert r.json()["username"] == "alice"
    assert r.json()["role"] == "user"


def test_sessions_are_scoped_to_their_owner(env):
    client, db = env
    alice = register(client, "alice")
    bob = register(client, "bob")

    sid = client.post("/api/session", headers=alice).json()["session_id"]
    client.post("/api/chat", headers=alice, json={"query": "what is the term?", "session_id": sid})

    alice_sessions = client.get("/api/sessions", headers=alice).json()["sessions"]
    bob_sessions = client.get("/api/sessions", headers=bob).json()["sessions"]

    assert any(s["session_id"] == sid for s in alice_sessions)
    assert sid not in [s["session_id"] for s in bob_sessions], "Bob can see Alice's session"


def test_cross_user_read_is_404_not_403(env):
    """IDOR guard: guessing another user's session ID must not reveal it exists."""
    client, _ = env
    alice = register(client, "alice")
    bob = register(client, "bob")

    sid = client.post("/api/session", headers=alice).json()["session_id"]
    client.post("/api/chat", headers=alice, json={"query": "termination clause?", "session_id": sid})

    for method, path, body in [
        ("get", f"/api/session/{sid}", None),
        ("get", f"/api/session/{sid}/chunks", None),
        ("get", f"/api/session/{sid}/graph", None),
        ("get", f"/api/session/{sid}/contracts", None),
        ("put", f"/api/session/{sid}/rename", {"title": "stolen"}),
        ("delete", f"/api/session/{sid}", None),
    ]:
        r = client.request(method, path, json=body, headers=bob)
        assert r.status_code == 404, f"{method.upper()} {path} -> {r.status_code}, expected 404"
        assert "not found" in r.json()["detail"].lower()


def test_cross_user_delete_does_not_destroy_data(env):
    client, db = env
    alice = register(client, "alice")
    bob = register(client, "bob")

    sid = client.post("/api/session", headers=alice).json()["session_id"]
    client.post("/api/chat", headers=alice, json={"query": "governing law?", "session_id": sid})

    assert client.delete(f"/api/session/{sid}", headers=bob).status_code == 404
    # Alice's history must survive the attempt
    still_there = client.get(f"/api/session/{sid}", headers=alice)
    assert still_there.status_code == 200
    assert len(still_there.json()["messages"]) == 2


def test_cross_user_chat_cannot_hijack_session(env):
    client, _ = env
    alice = register(client, "alice")
    bob = register(client, "bob")

    sid = client.post("/api/session", headers=alice).json()["session_id"]
    r = client.post("/api/chat", headers=bob, json={"query": "mine now", "session_id": sid})
    assert r.status_code == 404, r.text


def test_activity_feed_is_scoped(env):
    client, _ = env
    alice = register(client, "alice")
    bob = register(client, "bob")

    sid_a = client.post("/api/session", headers=alice).json()["session_id"]
    client.post("/api/chat", headers=alice, json={"query": "alice question", "session_id": sid_a})

    sid_b = client.post("/api/session", headers=bob).json()["session_id"]
    client.post("/api/chat", headers=bob, json={"query": "bob question", "session_id": sid_b})

    bobs_activity = client.get("/api/activity", headers=bob).json()["activity"]
    text = " ".join(a.get("title", "") for a in bobs_activity)
    assert "alice" not in text.lower(), "Alice's activity leaked into Bob's feed"


def test_overview_is_scoped(env):
    client, _ = env
    alice = register(client, "alice")
    bob = register(client, "bob")

    sid_a = client.post("/api/session", headers=alice).json()["session_id"]
    client.post("/api/chat", headers=alice, json={"query": "alice question", "session_id": sid_a})

    bobs_overview = client.get("/api/overview/summary", headers=bob).json()
    assert bobs_overview["total_contracts"] == 0
    assert sid_a not in [s["session_id"] for s in bobs_overview["session_distribution"]]


# ─── Roles ────────────────────────────────────────────────────────────

def test_non_admin_cannot_list_users(env, monkeypatch):
    client, db = env
    register(client, "alice")
    r = client.get("/api/admin/users", headers={"Authorization": "Bearer " + client.post(
        "/api/login", json={"username": "alice", "password": "correct-horse"}).json()["token"]})
    assert r.status_code == 403, r.text


def test_admin_can_list_users(env):
    client, db = env
    db[config.USERS_COLLECTION].insert_one(
        {"_id": "1", "username": "root", "password": security.hash_password("x-password"), "role": "admin"}
    )
    token = security.create_access_token("root", "admin")
    r = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    names = [u["username"] for u in r.json()["users"]]
    assert "root" in names
    assert all("password" not in u for u in r.json()["users"]), "password hash leaked"


# ─── Router structure ────────────────────────────────────────────────

def test_documented_route_set_is_stable(env):
    """A regression guard: catches accidental route renames during refactors.

    Uses the OpenAPI schema rather than app.routes, because newer FastAPI
    versions nest include_router results instead of flattening them.
    """
    client, _ = env
    documented = sorted(client.app.openapi()["paths"].keys())
    assert documented == sorted(
        [
            "/api/health",
            "/api/login",
            "/api/me",
            "/api/register",
            "/api/session",
            "/api/sessions",
            "/api/activity",
            "/api/chat",
            "/api/overview/summary",
            "/api/session/{session_id}",
            "/api/session/{session_id}/rename",
            "/api/session/{session_id}/ingest",
            "/api/session/{session_id}/chunks",
            "/api/session/{session_id}/graph",
            "/api/session/{session_id}/contracts",
            "/api/admin/users",
        ]
    ), f"documented routes changed: {documented}"


def test_router_layout(env):
    """Each concern lives in its own module under src/api/."""
    from src.api import admin, auth, chat, documents, overview, sessions

    for module, prefix in [
        (auth, "/api"),
        (sessions, "/api"),
        (documents, "/api/session/{session_id}"),
        (chat, "/api"),
        (overview, "/api"),
        (admin, "/api/admin"),
    ]:
        assert module.router.prefix == prefix, f"{module.__name__} prefix drift"
        assert module.router.routes, f"{module.__name__} exposes no routes"


# ─── ChatMemory ownership unit tests ──────────────────────────────────

def test_owns_session_rejects_other_users():
    client = mongomock.MongoClient()
    mem = ChatMemory(client["db"])
    sid = mem.create_session(user_id="alice")
    assert mem.owns_session(sid, "alice") is True
    assert mem.owns_session(sid, "bob") is False


def test_legacy_sessions_are_not_claimed():
    """A session with no user_id must not be handed to a logged-in user."""
    client = mongomock.MongoClient()
    mem = ChatMemory(client["db"])
    mem.col.insert_one({"_id": "legacy-1", "title": "old", "messages": []})
    # The document has no user_id, so no real owner matches it.
    assert mem.owns_session("legacy-1", "alice") is False
    assert mem.owns_session("legacy-1", "bob") is False
    # And it is not reachable through the scoped CRUD helpers either.
    assert mem.has_session("legacy-1", user_id="alice") is False
    assert mem.get_history("legacy-1", user_id="alice") == []
    assert mem.delete_session("legacy-1", user_id="alice") is False


def test_unknown_session_is_not_claimable():
    """An arbitrary client-supplied session_id must never be adopted."""
    client = mongomock.MongoClient()
    mem = ChatMemory(client["db"])
    assert mem.owns_session("never-persisted", "anyone") is False
    assert mem.owns_session(str(__import__("uuid").uuid4()), "alice") is False


def test_empty_sessions_hidden_from_listing():
    """Eager creation must not flood the user's history with empty shells."""
    client = mongomock.MongoClient()
    mem = ChatMemory(client["db"])
    empty = mem.create_session(user_id="alice")
    used = mem.create_session(user_id="alice")
    mem.append(used, "user", "hello", user_id="alice")

    visible = {s["session_id"] for s in mem.list_sessions(user_id="alice", include_empty=False)}
    assert used in visible
    assert empty not in visible


def test_chat_without_session_id_creates_owned_session(env):
    client, _ = env
    alice = register(client, "alice")
    r = client.post("/api/chat", headers=alice, json={"query": "no session id supplied"})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    # the new session belongs to Alice and is immediately usable
    assert client.get(f"/api/session/{sid}", headers=alice).status_code == 200


def test_client_supplied_foreign_uuid_is_rejected(env):
    """The attack the strict-ownership change closes."""
    client, _ = env
    alice = register(client, "alice")
    bob = register(client, "bob")

    import uuid as _uuid

    invented = str(_uuid.uuid4())
    r = client.post("/api/chat", headers=bob, json={"query": "hijack", "session_id": invented})
    assert r.status_code == 404, r.text
