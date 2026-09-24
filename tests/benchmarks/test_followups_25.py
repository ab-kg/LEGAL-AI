import os
import sys
import time
import pandas as pd
from datetime import datetime
from pymongo import MongoClient
import certifi

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# IPv4 patch applied via conftest.py
from src.core.common.utils import force_ipv4
force_ipv4()

from src.core.common import config
from src.core.rag.chat_memory import ChatMemory
from src.core.rag_pipeline import LegalGraphRAG

import json

def save_reports(records, json_path, report_path):
    """Saves progress to both JSON and Markdown formats for Followups."""
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
        
    llm_model_name = f"{config.GEMINI_MODEL} (Google)" if config.LLM_PROVIDER == "gemini" else f"{config.GROQ_MODEL} (Groq)"
    report_lines = [
        "# 💬 Followups 25 Benchmark Report\n",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Model:** {llm_model_name} (using {config.LLM_PROVIDER.upper()} provider)  \n",
        "---\n"
    ]
    for r in records:
        scenario = r["scenario"]
        difficulty = r["difficulty"]
        report_lines.append(f"## Scenario {scenario} ({difficulty})\n")
        
        for t_idx, turn in enumerate(r["turns"], 1):
            q = turn["query"]
            ans = turn["answer"]
            latency = turn["latency"]
            
            turn_name = f"Turn {t_idx}"
            if t_idx == 2:
                turn_name = "Turn 2 (Follow-up 1)"
            elif t_idx == 3:
                turn_name = "Turn 3 (Follow-up 2)"
                
            report_lines.append(f"### {turn_name}: {q}\n")
            report_lines.append(f"**Latency:** {latency:.2f}s  \n")
            report_lines.append(f"> {ans}\n\n")
            
        report_lines.append("---\n\n")
        
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

def main():
    print("==================================================")
    print("    LEGAL AI - FOLLOWUPS 25 BENCHMARK TEST")
    print("==================================================")

    start_time = time.time()

    csv_path = "resources/benchmark_queries/GraphRAG_Followups_25.csv"
    if not os.path.exists(csv_path):
        print(f"❌ ERROR: File not found at {csv_path}")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} follow-up scenarios from {csv_path}")

    # Connect to MongoDB for session memory
    assert config.MONGO_URI, "MONGO_URI must be set"
    client = MongoClient(config.MONGO_URI, tlsCAFile=certifi.where())
    db = client["legal_rag"]
    memory = ChatMemory(db)
    print("✅ Connected to MongoDB Atlas for Chat Memory.")

    # Boot the RAG engine
    print("Booting LegalGraphRAG Engine...")
    engine = LegalGraphRAG()
    print("✅ Engine Ready!")

    # Setup directories and paths
    os.makedirs("resources/reports", exist_ok=True)
    json_path = "resources/reports/followups_25_report.json"
    report_path = "resources/reports/followups_25_report.md"

    # Resuming logic
    records = []
    completed_scenarios = set()
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                records = json.load(f)
            completed_scenarios = {str(r["scenario"]) for r in records}
            print(f"🔄 Resuming benchmark: {len(completed_scenarios)} scenarios already answered.")
        except Exception as e:
            print(f"⚠️ Warning: Failed to load existing report: {e}. Starting fresh.")
            records = []

    total_scenarios = len(df)
    
    try:
        for idx, row in df.iterrows():
            scenario = row.get("Scenario")
            difficulty = row.get("Difficulty")
            q_init = row.get("Initial Query")
            q_f1 = row.get("Follow-up 1")
            q_f2 = row.get("Follow-up 2")

            # Check if this scenario was already completed in a previous run
            if str(scenario) in completed_scenarios:
                continue

            # Graceful timeout check: 39 minutes = 2340 seconds
            elapsed_time = time.time() - start_time
            if elapsed_time > 2340:
                print(f"\n⏳ Time limit of 40 minutes approaching ({elapsed_time:.1f}s elapsed). Saving current progress and exiting gracefully.")
                break

            print(f"\n[{idx+1}/{total_scenarios}] Running Scenario {scenario} ({difficulty})")
            
            # Create a unique session ID
            session_id = f"test_bench_scenario_{scenario}"
            
            # Clean up any leftover session
            memory.delete_session(session_id)
            memory.create_session(session_id)
            
            scenario_record = {
                "scenario": scenario,
                "difficulty": difficulty,
                "turns": []
            }

            try:
                # Turn 1: Initial Query
                print(f"  Turn 1: {q_init[:50]}...")
                t0 = time.time()
                ans_init, ctx_init, tri_init = engine.answer_query(q_init)
                latency_init = time.time() - t0
                memory.append(session_id, "user", q_init)
                memory.append(session_id, "assistant", ans_init)
                scenario_record["turns"].append({
                    "query": q_init,
                    "answer": ans_init,
                    "latency": latency_init
                })
                time.sleep(3.0)

                # Turn 2: Follow-up 1
                print(f"  Turn 2: {q_f1[:50]}...")
                t0 = time.time()
                history = memory.get_history(session_id)
                ans_f1, ctx_f1, tri_f1 = engine.answer_query(q_f1, chat_history=history)
                latency_f1 = time.time() - t0
                memory.append(session_id, "user", q_f1)
                memory.append(session_id, "assistant", ans_f1)
                scenario_record["turns"].append({
                    "query": q_f1,
                    "answer": ans_f1,
                    "latency": latency_f1
                })
                time.sleep(3.0)

                # Turn 3: Follow-up 2
                print(f"  Turn 3: {q_f2[:50]}...")
                t0 = time.time()
                history = memory.get_history(session_id)
                ans_f2, ctx_f2, tri_f2 = engine.answer_query(q_f2, chat_history=history)
                latency_f2 = time.time() - t0
                memory.append(session_id, "user", q_f2)
                memory.append(session_id, "assistant", ans_f2)
                scenario_record["turns"].append({
                    "query": q_f2,
                    "answer": ans_f2,
                    "latency": latency_f2
                })

            except Exception as e:
                # If a turn fails, save the exception info and move on
                print(f"❌ Error in Scenario {scenario}: {e}")
                scenario_record["turns"].append({
                    "query": "ERROR",
                    "answer": f"Scenario execution failed: {e}",
                    "latency": 0.0
                })
            finally:
                # Cleanup session
                memory.delete_session(session_id)

            records.append(scenario_record)
            
            # Save progress incrementally after every scenario
            save_reports(records, json_path, report_path)
            
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
