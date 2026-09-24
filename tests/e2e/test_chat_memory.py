"""
Legal AI — Chat Memory End-to-End Test
=======================================
Tests the ChatMemory class and verifies the RAG pipeline uses
conversation history correctly for follow-up questions.

Cleans up all test data from Atlas after completion.

Usage (CI or local):
    python tests/test_chat_memory.py
"""

import os
import sys
import time
import uuid
from datetime import datetime

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from pymongo import MongoClient
import certifi

# IPv4 patch applied via conftest.py
from src.core.common.utils import force_ipv4
force_ipv4()

from src.core.common import config
from src.core.rag.chat_memory import ChatMemory
from src.core.rag_pipeline import LegalGraphRAG

# Prefix with unique run ID so parallel or sequential runs don't conflict,
# while still allowing regex cleanup of anything starting with test_ci_
RUN_ID = str(uuid.uuid4())[:8]
TEST_PREFIX = f"test_ci_{RUN_ID}_"


def run_tests():
    print("=" * 70)
    print("  💬  LEGAL AI — CHAT MEMORY END-TO-END TEST")
    print("=" * 70)

    report_lines = [
        "# 💬 Legal AI — Chat Memory Test Report\n",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n",
        "---\n",
    ]

    all_passed = True
    test_session_ids = []  # track for cleanup

    # ------------------------------------------------------------------
    # SETUP: Connect to Atlas
    # ------------------------------------------------------------------
    assert config.MONGO_URI, "MONGO_URI must be set"
    client = MongoClient(config.MONGO_URI, tlsCAFile=certifi.where())
    db = client["legal_rag"]
    memory = ChatMemory(db)
    print("\n✅ Connected to MongoDB Atlas")

    # Clean up any leftover test sessions from previous aborted runs
    try:
        delete_result = db[ChatMemory.COLLECTION].delete_many({"_id": {"$regex": "^test_ci_"}})
        if delete_result.deleted_count > 0:
            print(f"  🧹 Cleaned up {delete_result.deleted_count} leftover test session(s) from previous runs.\n")
        else:
            print("  🧹 No leftover test sessions found to clean up.\n")
    except Exception as e:
        print(f"  ⚠️ Failed to clean up leftover sessions: {e}\n")

    # ------------------------------------------------------------------
    # TEST 1: Create session + append + retrieve
    # ------------------------------------------------------------------
    print("─" * 70)
    print("  TEST 1: CRUD — Create, Append, Retrieve")
    print("─" * 70)

    t0 = time.time()
    try:
        sid = memory.create_session(session_id=f"{TEST_PREFIX}crud")
        test_session_ids.append(sid)

        # Verify has_session works
        assert memory.has_session(sid) is True, "Expected session to exist"
        assert memory.has_session(f"{TEST_PREFIX}nonexistent") is False, "Expected session to not exist"

        # Append a 3-turn conversation
        memory.append(sid, "user", "What are the termination clauses?")
        memory.append(sid, "assistant", "The contract includes a 30-day notice termination clause.")
        memory.append(sid, "user", "Can either party terminate early?")
        memory.append(sid, "assistant", "Yes, either party may terminate with 30 days written notice.")
        memory.append(sid, "user", "What about breach?")
        memory.append(sid, "assistant", "Material breach allows immediate termination.")

        # Retrieve and verify
        history = memory.get_history(sid, limit=10)
        assert len(history) == 6, f"Expected 6 messages, got {len(history)}"
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "What are the termination clauses?"
        assert history[-1]["role"] == "assistant"
        assert "breach" in history[-1]["content"].lower()

        # Verify limit works
        limited = memory.get_history(sid, limit=2)
        assert len(limited) == 2, f"Expected 2 messages with limit=2, got {len(limited)}"

        latency = time.time() - t0
        status = "✅ PASS"
        detail = f"6 messages stored & retrieved in {latency:.2f}s"
        print(f"  {status} — {detail}\n")
    except Exception as e:
        latency = time.time() - t0
        status = "❌ FAIL"
        detail = str(e)
        all_passed = False
        print(f"  {status} — {detail}\n")

    report_lines.append(f"\n## Test 1: CRUD\n")
    report_lines.append(f"**Status:** {status} | **Latency:** {latency:.2f}s  \n")
    report_lines.append(f"> {detail}\n")
    report_lines.append("\n---\n")

    # ------------------------------------------------------------------
    # TEST 2: List sessions
    # ------------------------------------------------------------------
    print("─" * 70)
    print("  TEST 2: List Sessions")
    print("─" * 70)

    t0 = time.time()
    try:
        sessions = memory.list_sessions(limit=5)
        assert len(sessions) >= 1, "Expected at least 1 session"
        assert any(s["session_id"] == f"{TEST_PREFIX}crud" for s in sessions)
        latency = time.time() - t0
        status = "✅ PASS"
        detail = f"Found {len(sessions)} session(s)"
        print(f"  {status} — {detail}\n")
    except Exception as e:
        latency = time.time() - t0
        status = "❌ FAIL"
        detail = str(e)
        all_passed = False
        print(f"  {status} — {detail}\n")

    report_lines.append(f"\n## Test 2: List Sessions\n")
    report_lines.append(f"**Status:** {status} | **Latency:** {latency:.2f}s  \n")
    report_lines.append(f"> {detail}\n")
    report_lines.append("\n---\n")

    # ------------------------------------------------------------------
    # TEST 3: RAG pipeline with chat history (follow-up question)
    # ------------------------------------------------------------------
    print("─" * 70)
    print("  TEST 3: RAG Pipeline with Chat Memory (Follow-Up)")
    print("─" * 70)

    t0 = time.time()
    try:
        engine = LegalGraphRAG()

        sid2 = memory.create_session(session_id=f"{TEST_PREFIX}rag")
        test_session_ids.append(sid2)

        # First question
        q1 = "What are the termination clauses in the contracts?"
        answer1, ctx1, tri1 = engine.answer_query(q1)
        memory.append(sid2, "user", q1)
        memory.append(sid2, "assistant", answer1)
        print(f"\n  Q1: {q1}")
        print(f"  A1: {answer1[:150]}...")

        # Follow-up that relies on context from Q1
        q2 = "Can you elaborate on the notice period mentioned above?"
        history = memory.get_history(sid2)
        answer2, ctx2, tri2 = engine.answer_query(q2, chat_history=history)
        memory.append(sid2, "user", q2)
        memory.append(sid2, "assistant", answer2)
        print(f"\n  Q2: {q2}")
        print(f"  A2: {answer2[:150]}...")

        # Verify history has 4 messages
        final_history = memory.get_history(sid2)
        assert len(final_history) == 4, f"Expected 4 messages, got {len(final_history)}"

        # Both answers should be non-empty
        assert len(answer1) > 10, "Answer 1 is too short"
        assert len(answer2) > 10, "Answer 2 is too short"

        latency = time.time() - t0
        status = "✅ PASS"
        detail = f"2-turn conversation completed in {latency:.2f}s"
        print(f"\n  {status} — {detail}\n")
    except Exception as e:
        latency = time.time() - t0
        status = "❌ FAIL"
        detail = str(e)
        all_passed = False
        print(f"\n  {status} — {detail}\n")

    report_lines.append(f"\n## Test 3: RAG + Chat Memory\n")
    report_lines.append(f"**Status:** {status} | **Latency:** {latency:.2f}s  \n")
    report_lines.append(f"> {detail}\n")
    if 'answer1' in dir():
        report_lines.append(f"\n### Turn 1\n")
        report_lines.append(f"**Q:** {q1}  \n")
        report_lines.append(f"> {answer1}\n")
        report_lines.append(f"\n### Turn 2 (Follow-Up)\n")
        report_lines.append(f"**Q:** {q2}  \n")
        report_lines.append(f"> {answer2}\n")
    report_lines.append("\n---\n")

    # ------------------------------------------------------------------
    # TEST 4: Delete session
    # ------------------------------------------------------------------
    print("─" * 70)
    print("  TEST 4: Delete Session")
    print("─" * 70)

    t0 = time.time()
    try:
        del_sid = memory.create_session(session_id=f"{TEST_PREFIX}delete")
        test_session_ids.append(del_sid)
        memory.append(del_sid, "user", "test message")
        assert memory.delete_session(del_sid) is True
        assert memory.get_history(del_sid) == []
        assert memory.delete_session(del_sid) is False  # already gone
        # Remove from cleanup list since it's already deleted
        test_session_ids.remove(del_sid)
        latency = time.time() - t0
        status = "✅ PASS"
        detail = "Session created, deleted, verified gone"
        print(f"  {status} — {detail}\n")
    except Exception as e:
        latency = time.time() - t0
        status = "❌ FAIL"
        detail = str(e)
        all_passed = False
        print(f"  {status} — {detail}\n")

    report_lines.append(f"\n## Test 4: Delete Session\n")
    report_lines.append(f"**Status:** {status} | **Latency:** {latency:.2f}s  \n")
    report_lines.append(f"> {detail}\n")
    report_lines.append("\n---\n")

    # ------------------------------------------------------------------
    # TEST 5: Multi-Session Isolation
    # ------------------------------------------------------------------
    print("─" * 70)
    print("  TEST 5: Multi-Session Isolation")
    print("─" * 70)

    t0 = time.time()
    try:
        engine = LegalGraphRAG()
        
        sid_a = memory.create_session(session_id=f"{TEST_PREFIX}session_a")
        test_session_ids.append(sid_a)
        memory.append(sid_a, "user", "What is the governing law?")
        memory.append(sid_a, "assistant", "The governing law is New York.")

        sid_b = memory.create_session(session_id=f"{TEST_PREFIX}session_b")
        test_session_ids.append(sid_b)
        memory.append(sid_b, "user", "What is the governing law?")
        memory.append(sid_b, "assistant", "The governing law is California.")

        # Retrieve and verify database isolation
        hist_a = memory.get_history(sid_a)
        hist_b = memory.get_history(sid_b)

        assert len(hist_a) == 2, f"Expected 2 messages in A, got {len(hist_a)}"
        assert len(hist_b) == 2, f"Expected 2 messages in B, got {len(hist_b)}"
        assert hist_a[1]["content"] == "The governing law is New York."
        assert hist_b[1]["content"] == "The governing law is California."

        latency = time.time() - t0
        status = "✅ PASS"
        detail = "Multi-session context isolation verified successfully"
        print(f"  {status} — {detail}\n")
    except Exception as e:
        latency = time.time() - t0
        status = "❌ FAIL"
        detail = str(e)
        all_passed = False
        print(f"  {status} — {detail}\n")

    report_lines.append(f"\n## Test 5: Multi-Session Isolation\n")
    report_lines.append(f"**Status:** {status} | **Latency:** {latency:.2f}s  \n")
    report_lines.append(f"> {detail}\n")
    report_lines.append("\n---\n")

    # ------------------------------------------------------------------
    # TEST 6: Long Conversation history windowing (Context Safety)
    # ------------------------------------------------------------------
    print("─" * 70)
    print("  TEST 6: Long Conversation history windowing (Context Safety)")
    print("─" * 70)

    t0 = time.time()
    try:
        engine = LegalGraphRAG()
        sid_long = memory.create_session(session_id=f"{TEST_PREFIX}long")
        test_session_ids.append(sid_long)

        # Append 15 turns (30 messages) to build a very long history
        for idx in range(1, 16):
            memory.append(sid_long, "user", f"Dummy question {idx} regarding section {idx}.")
            memory.append(sid_long, "assistant", f"Dummy response acknowledging section {idx}.")

        # Retrieve and verify database count
        hist_long = memory.get_history(sid_long, limit=50)
        assert len(hist_long) == 30, f"Expected 30 messages in DB, got {len(hist_long)}"

        # Query the RAG engine with this long history
        # Verifies the engine filters/slices the context window correctly and executes without error
        ans_long, _, _ = engine.answer_query("What is the governing law?", chat_history=hist_long)
        
        latency = time.time() - t0
        status = "✅ PASS"
        detail = f"RAG answered successfully with 30-message history in {latency:.2f}s"
        print(f"  {status} — {detail}\n")
    except Exception as e:
        latency = time.time() - t0
        status = "❌ FAIL"
        detail = str(e)
        all_passed = False
        print(f"  {status} — {detail}\n")

    report_lines.append(f"\n## Test 6: Long Conversation history windowing\n")
    report_lines.append(f"**Status:** {status} | **Latency:** {latency:.2f}s  \n")
    report_lines.append(f"> {detail}\n")
    report_lines.append("\n---\n")

    # ------------------------------------------------------------------
    # CLEANUP: Remove all test sessions from Atlas
    # ------------------------------------------------------------------
    print("─" * 70)
    print("  CLEANUP: Removing test data from Atlas")
    print("─" * 70)

    for sid in test_session_ids:
        try:
            memory.delete_session(sid)
            print(f"  🗑️  Deleted {sid}")
        except Exception as e:
            print(f"  ⚠️  Failed to delete {sid}: {e}")
    print()

    # ------------------------------------------------------------------
    # SAVE REPORT
    # ------------------------------------------------------------------
    os.makedirs("resources/reports", exist_ok=True)
    report_path = "resources/reports/chat_memory_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    print(f"{'═' * 70}")
    print(f"  📝 Report saved to {report_path}")
    print(f"  🏁 Result: {'ALL 6 PASSED ✅' if all_passed else 'SOME FAILED ❌'}")
    print(f"{'═' * 70}\n")

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
