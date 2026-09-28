"""Full-stack test against the live server with the REAL RAG engine:
sign up -> sign in -> ingest a real contract PDF -> ask a real question.
"""

import json
import pathlib
import sys

import httpx

BASE = "http://127.0.0.1:8000"
ROOT = pathlib.Path(r"C:\Users\harsh\Desktop\AB-KG\PROJECTS\LEGAL-AI")
PDF = ROOT / "sample_software_license_agreement.pdf"
USER, PASSWORD = "ragtest_user", "ragtest-pass-1"

fails = []


def check(label, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}{('  -> ' + str(detail)[:120]) if detail else ''}", flush=True)
    if not ok:
        fails.append(label)


c = httpx.Client(base_url=BASE, timeout=300)

# ─── auth ────────────────────────────────────────────────────────────
r = c.post("/api/register", json={"username": USER, "password": PASSWORD})
if r.status_code == 409:
    print("      (user exists, reusing)", flush=True)
else:
    check("signup -> 201", r.status_code == 201, r.text[:90])

r = c.post("/api/login", json={"username": USER, "password": PASSWORD})
check("signin -> 200 + token", r.status_code == 200 and bool(r.json().get("token")), r.text[:80])
auth = {"Authorization": f"Bearer {r.json()['token']}"}

check("anonymous still blocked", httpx.get(f"{BASE}/api/sessions", timeout=30).status_code == 401)

sid = c.post("/api/session", headers=auth).json()["session_id"]
print(f"\n      session: {sid}\n", flush=True)

# ─── real PDF ingestion ──────────────────────────────────────────────
check("sample PDF exists", PDF.exists(), PDF.name)
with PDF.open("rb") as fh:
    r = c.post(
        f"/api/session/{sid}/ingest",
        headers=auth,
        files={"file": (PDF.name, fh, "application/pdf")},
    )
check("ingest real PDF -> 201", r.status_code == 201, r.text[:160])

# ─── did it actually index anything? ──────────────────────────────────
r = c.get(f"/api/session/{sid}/chunks", headers=auth)
data = r.json()
check("chunks were created", data.get("has_pdf") and data.get("chunks_count", 0) > 0,
      f"chunks_count={data.get('chunks_count')}")
print(f"      contracts: {data.get('contracts')}", flush=True)
if data.get("chunks"):
    print(f"      sample: {data['chunks'][0]['text_snippet'][:110]}...\n", flush=True)

r = c.get(f"/api/session/{sid}/graph", headers=auth)
g = r.json()
check("knowledge graph built", g.get("nodes_count", 0) > 0,
      f"nodes={g.get('nodes_count')} edges={g.get('edges_count')}")

r = c.get(f"/api/session/{sid}/contracts", headers=auth)
check("contract metadata extracted", r.json().get("contracts_count", 0) > 0,
      r.json().get("contracts_count"))

# ─── real RAG question ───────────────────────────────────────────────
print("\n      asking a real question (hits Groq)...\n", flush=True)
r = c.post("/api/chat", headers=auth, json={
    "query": "What is the governing law of this agreement?",
    "session_id": sid,
})
check("chat -> 200", r.status_code == 200, r.text[:90])
if r.status_code == 200:
    body = r.json()
    answer = body.get("answer", "")
    check("answer is not an error/placeholder",
          "RAG engine is disabled" not in answer and len(answer) > 40,
          f"{len(answer)} chars")
    check("retrieved context came back", len(body.get("contexts", [])) > 0,
          f"{len(body.get('contexts', []))} contexts")
    print("\n" + "=" * 66)
    print("ANSWER:", answer[:600])
    print("=" * 66)
    if body.get("triplets"):
        print("KG TRIPLETS:", body["triplets"][:4])

# ─── follow-up turn exercises history + query condensation ───────────
print("\n      follow-up question (tests query condensation)...\n", flush=True)
r = c.post("/api/chat", headers=auth, json={
    "query": "What about termination?",
    "session_id": sid,
})
check("follow-up -> 200", r.status_code == 200, r.text[:80])

r = c.get(f"/api/session/{sid}", headers=auth)
msgs = r.json().get("messages", [])
# 1 welcome message appended by ingestion, then 2 chat turns x (user + assistant).
check("history holds the expected turns", len(msgs) == 5,
      f"{len(msgs)} messages (1 welcome + 2 turns x 2)")
check("history alternates user/assistant after the welcome",
      [m["role"] for m in msgs[1:]] == ["user", "assistant", "user", "assistant"],
      [m["role"] for m in msgs])

# ─── dashboard ───────────────────────────────────────────────────────
r = c.get("/api/overview/summary", headers=auth)
check("overview -> 200", r.status_code == 200, r.text[:90])
r = c.get("/api/activity", headers=auth)
check("activity -> 200", r.status_code == 200)

c.delete(f"/api/session/{sid}", headers=auth)
print("\n" + "=" * 66)
print(f"{len(fails)} FAILURE(S): " + ", ".join(fails) if fails else "FULL RAG STACK VERIFIED")
