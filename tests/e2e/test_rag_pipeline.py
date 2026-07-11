"""
Legal AI — End-to-End RAG Pipeline Test
========================================
Boots the LegalGraphRAG engine, runs 3 diverse legal questions, and
prints the full context breakdown (KG node details, KG triples, VDB
semantic chunks) alongside the LLM answer.

Saves a markdown report to resources/reports/rag_pipeline_report.md.

Usage (CI or local):
    python tests/test_rag_pipeline.py
"""

import os
import sys
import time
from datetime import datetime

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from src.core.common import config
from src.core.rag_pipeline import LegalGraphRAG

# =====================================================================
# TEST QUESTIONS — chosen to exercise different retrieval paths
# =====================================================================
TEST_QUESTIONS = [
    "What are the termination clauses in the contracts?",
    "Which parties are involved and what is the governing law?",
    "What is the limitation of liability and indemnification?",
]


def run_tests():
    print("=" * 70)
    print("  🏛️  LEGAL AI — END-TO-END RAG PIPELINE TEST")
    print("=" * 70)

    # --- 1. Boot Engine ---
    print("\n[1/2] Initializing LegalGraphRAG Engine...")
    t0 = time.time()
    engine = LegalGraphRAG()
    boot_time = time.time() - t0
    print(f"  ✅ Engine ready in {boot_time:.1f}s\n")

    # --- 2. Run Questions ---
    print("[2/2] Running 3 test questions...\n")

    llm_model_name = f"{config.GEMINI_MODEL} (Google)" if config.LLM_PROVIDER == "gemini" else f"{config.GROQ_MODEL} (Groq)"
    report_lines = [
        "# 🏛️ Legal AI — RAG Pipeline Test Report\n",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Engine boot:** {boot_time:.1f}s  ",
        f"**Model:** {llm_model_name} (using {config.LLM_PROVIDER.upper()} provider)  \n",
        "---\n",
    ]

    all_passed = True

    for i, question in enumerate(TEST_QUESTIONS, 1):
        print(f"{'─' * 70}")
        print(f"  QUESTION {i}: {question}")
        print(f"{'─' * 70}")

        t_start = time.time()
        try:
            answer, contexts, triplets = engine.answer_query(question)
            latency = time.time() - t_start
            status = "✅ PASS"
        except Exception as e:
            latency = time.time() - t_start
            answer = f"ERROR: {e}"
            contexts = []
            triplets = []
            status = "❌ FAIL"
            all_passed = False

        # --- Console Output ---
        print(f"\n  ⏱️  Latency: {latency:.2f}s | Status: {status}")

        # KG Triples
        print(f"\n  📊 KG Triples ({len(triplets)}):")
        if triplets:
            for t in triplets[:10]:  # cap at 10 for readability
                print(f"    • {t}")
            if len(triplets) > 10:
                print(f"    ... and {len(triplets) - 10} more")
        else:
            print("    (none)")

        # VDB Semantic Chunks
        print(f"\n  📄 VDB Semantic Chunks ({len(contexts)}):")
        if contexts:
            for j, ctx in enumerate(contexts[:3], 1):  # cap at 3 previews
                preview = ctx.strip().replace("\n", " ")[:200]
                print(f"    [{j}] {preview}...")
            if len(contexts) > 3:
                print(f"    ... and {len(contexts) - 3} more")
        else:
            print("    (none)")

        # LLM Answer
        print(f"\n  🤖 Answer:")
        for line in answer.split("\n"):
            print(f"    {line}")
        print()

        # --- Report Section ---
        report_lines.append(f"\n## Question {i}: {question}\n")
        report_lines.append(f"**Latency:** {latency:.2f}s | **Status:** {status}\n")

        report_lines.append(f"\n### KG Context ({len(triplets)} triples)\n")
        if triplets:
            report_lines.append("```")
            for t in triplets:
                report_lines.append(t)
            report_lines.append("```\n")
        else:
            report_lines.append("_(no KG triples matched)_\n")

        report_lines.append(f"\n### VDB Context ({len(contexts)} chunks)\n")
        if contexts:
            for j, ctx in enumerate(contexts, 1):
                preview = ctx.strip().replace("\n", " ")[:300]
                report_lines.append(f"**Chunk {j}:**")
                report_lines.append(f"> {preview}{'...' if len(ctx.strip()) > 300 else ''}\n")
        else:
            report_lines.append("_(no semantic chunks retrieved)_\n")

        report_lines.append(f"\n### LLM Answer\n")
        report_lines.append(f"> {answer}\n")
        report_lines.append("\n---\n")

    # --- Save Report ---
    os.makedirs("resources/reports", exist_ok=True)
    report_path = "resources/reports/rag_pipeline_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    print(f"{'═' * 70}")
    print(f"  📝 Report saved to {report_path}")
    print(f"  🏁 Result: {'ALL 3 PASSED ✅' if all_passed else 'SOME FAILED ❌'}")
    print(f"{'═' * 70}\n")

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
