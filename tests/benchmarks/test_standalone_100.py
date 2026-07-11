import os
import sys
import time
import pandas as pd
from datetime import datetime

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# IPv4 patch applied via conftest.py
from src.core.common.utils import force_ipv4
force_ipv4()

from src.core.common import config
from src.core.rag_pipeline import LegalGraphRAG

import json

def save_reports(records, json_path, report_path):
    """Saves progress to both JSON and Markdown formats."""
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
        
    llm_model_name = f"{config.GEMINI_MODEL} (Google)" if config.LLM_PROVIDER == "gemini" else f"{config.GROQ_MODEL} (Groq)"
    report_lines = [
        "# 📊 Standalone 100 Benchmark Report\n",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Model:** {llm_model_name}  \n",
        "---\n"
    ]
    for r in records:
        q_id = r["id"]
        difficulty = r["difficulty"]
        question = r["question"]
        answer = r["answer"]
        latency = r["latency"]
        status = r.get("status", "✅ SUCCESS")
        contexts_count = r["contexts_count"]
        triplets_count = r["triplets_count"]
        triplets = r.get("triplets", [])
        
        report_lines.append(f"### Q{q_id} ({difficulty}): {question}\n")
        report_lines.append(f"**Latency:** {latency:.2f}s | **Status:** {status} | **Vector Chunks:** {contexts_count} | **KG Triples:** {triplets_count}\n\n")
        report_lines.append(f"#### Generated Answer\n> {answer}\n\n")
        if triplets:
            report_lines.append("#### Matched Graph Triples\n```\n" + "\n".join(triplets[:5]) + ("\n... and more" if len(triplets) > 5 else "") + "\n```\n\n")
        report_lines.append("---\n\n")
        
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

def main():
    print("==================================================")
    print("   LEGAL AI - STANDALONE 100 BENCHMARK TEST")
    print("==================================================")

    start_time = time.time()

    csv_path = "resources/benchmark_queries/GraphRAG_Standalone_100.csv"
    if not os.path.exists(csv_path):
        print(f"❌ ERROR: File not found at {csv_path}")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} standalone queries from {csv_path}")

    # Boot the engine
    print("Booting LegalGraphRAG Engine...")
    engine = LegalGraphRAG()
    print("✅ Engine Ready!")

    # We use resources/reports for saving progress
    os.makedirs("resources/reports", exist_ok=True)
    json_path = "resources/reports/standalone_100_report.json"
    report_path = "resources/reports/standalone_100_report.md"

    # Resuming logic
    records = []
    completed_ids = set()
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                records = json.load(f)
            completed_ids = {int(r["id"]) for r in records}
            print(f"🔄 Resuming benchmark: {len(completed_ids)} queries already answered.")
        except Exception as e:
            print(f"⚠️ Warning: Failed to load existing report: {e}. Starting fresh.")
            records = []

    total_queries = len(df)
    
    try:
        for idx, row in df.iterrows():
            q_id = int(row.get("ID"))
            difficulty = row.get("Difficulty")
            question = row.get("Question")

            # Check if this query was already completed in a previous run
            if q_id in completed_ids:
                continue

            # Graceful timeout check: 39 minutes = 2340 seconds
            elapsed_time = time.time() - start_time
            if elapsed_time > 2340:
                print(f"\n⏳ Time limit of 40 minutes approaching ({elapsed_time:.1f}s elapsed). Saving current progress and exiting gracefully.")
                break

            print(f"[{idx+1}/{total_queries}] Running Q{q_id} ({difficulty}): {question[:60]}...")
            t0 = time.time()
            try:
                answer, contexts, triplets = engine.answer_query(question)
                latency = time.time() - t0
                status = "✅ SUCCESS"
            except Exception as e:
                answer = f"ERROR: {e}"
                contexts = []
                triplets = []
                latency = time.time() - t0
                status = "❌ FAILED"

            print(f"  Status: {status} | Latency: {latency:.2f}s | Context Chunks: {len(contexts)} | KG Triples: {len(triplets)}")

            # Store record
            records.append({
                "id": q_id,
                "difficulty": difficulty,
                "question": question,
                "answer": answer,
                "latency": latency,
                "status": status,
                "contexts_count": len(contexts),
                "triplets_count": len(triplets),
                "triplets": triplets
            })

            # Save progress incrementally after every query
            save_reports(records, json_path, report_path)

            # Small delay to avoid Groq rate limit
            time.sleep(3.0)

    except KeyboardInterrupt:
        print("\n🛑 Benchmark execution interrupted by user.")
    finally:
        # Final save to ensure all data is written and formatted correctly
        save_reports(records, json_path, report_path)
        print(f"\n📝 Markdown report saved to {report_path}")
        print(f"📁 JSON data saved to {json_path}")

if __name__ == "__main__":
    main()
