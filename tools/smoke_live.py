"""Live smoke test: boots the real server in-process, drives it over HTTP,
then shuts it down. Avoids the process-tree issues of Start-Process."""

import os
import sys
import threading
import time

os.environ.setdefault("LEGAL_AI_SKIP_RAG", "1")
os.environ.setdefault("MONGO_DB_NAME", "legal_rag_smoketest")
os.environ.setdefault("JWT_SECRET", "smoke-test-secret-0123456789abcdef0123456789abcdef")
os.environ.setdefault("ADMIN_USERNAME", "")
os.environ.setdefault("ADMIN_PASSWORD", "")

sys.path.insert(0, r"C:\Users\harsh\Desktop\AB-KG\PROJECTS\LEGAL-AI")

import httpx
import uvicorn

PORT = 8891
BASE = f"http://127.0.0.1:{PORT}"
USER, PASSWORD = "smoketest_user", "smoke-pass-123"

fails = []


def check(label, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}{('  -> ' + str(detail)[:100]) if detail else ''}", flush=True)
    if not ok:
        fails.append(label)


from src.app import app

config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
server = uvicorn.Server(config)
server.install_signal_handlers = lambda: None
thread = threading.Thread(target=server.run, daemon=True)
thread.start()

deadline = time.time() + 90
while not server.started and time.time() < deadline:
    time.sleep(0.5)
if not server.started:
    print("server failed to start")
    sys.exit(1)
print("=== server started ===\n", flush=True)

try:
    c = httpx.Client(base_url=BASE, timeout=30)

    r = c.get("/api/health")
    check("GET /api/health (public)", r.status_code == 200, r.text)

    r = c.get("/login.html")
    check("login page served + has Create Account tab",
          r.status_code == 200 and "tab-register" in r.text, r.status_code)

    for path in ["/api/sessions", "/api/overview/summary", "/api/activity", "/api/me"]:
        check(f"anonymous {path} -> 401", c.get(path).status_code == 401)
    check("anonymous POST /api/chat -> 401", c.post("/api/chat", json={"query": "hi"}).status_code == 401)

    r = c.post("/api/register", json={"username": USER, "password": PASSWORD})
    if r.status_code == 409:
        print("      (user already exists; reusing)", flush=True)
    else:
        check("signup -> 201 + token", r.status_code == 201 and bool(r.json().get("token")), r.text[:80])

    check("duplicate signup -> 409",
          c.post("/api/register", json={"username": USER, "password": PASSWORD}).status_code == 409)
    check("weak password -> 422",
          c.post("/api/register", json={"username": "weakpw", "password": "short"}).status_code == 422)

    r = c.post("/api/login", json={"username": USER, "password": PASSWORD})
    check("signin -> 200 + token", r.status_code == 200 and bool(r.json().get("token")), r.text[:80])
    token = r.json()["token"]
    auth = {"Authorization": f"Bearer {token}"}

    check("wrong password -> 401",
          c.post("/api/login", json={"username": USER, "password": "nope-nope-nope"}).status_code == 401)
    check("garbage token -> 401",
          c.get("/api/me", headers={"Authorization": "Bearer a.b.c"}).status_code == 401)

    r = c.get("/api/me", headers=auth)
    check("/api/me identifies the caller", r.status_code == 200 and r.json().get("username") == USER, r.text[:70])

    sid = c.post("/api/session", headers=auth).json()["session_id"]
    r = c.post("/api/chat", headers=auth, json={"query": "what is the term?", "session_id": sid})
    check("chat -> 200 and echoes session", r.status_code == 200 and r.json().get("session_id") == sid, r.text[:70])

    r = c.get(f"/api/session/{sid}", headers=auth)
    check("history has both turns", r.status_code == 200 and len(r.json()["messages"]) == 2, len(r.json()["messages"]))

    ids = [s["session_id"] for s in c.get("/api/sessions", headers=auth).json()["sessions"]]
    check("session listed for its owner", sid in ids, ids)

    check("overview -> 200", c.get("/api/overview/summary", headers=auth).status_code == 200)
    check("activity -> 200", c.get("/api/activity", headers=auth).status_code == 200)
    check("non-admin blocked from /api/admin/users", c.get("/api/admin/users", headers=auth).status_code == 403)

    r = c.delete(f"/api/session/{sid}", headers=auth)
    check("DELETE session -> 200", r.status_code == 200, r.text[:60])

    print("\n" + "=" * 62)
    print(f"{len(fails)} FAILURE(S): " + ", ".join(fails) if fails else "ALL LIVE CHECKS PASSED")
finally:
    server.should_exit = True
    thread.join(timeout=15)
