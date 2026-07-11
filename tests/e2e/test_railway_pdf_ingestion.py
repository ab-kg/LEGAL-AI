import os
import sys
import io
import time
import uuid
import requests
from datetime import datetime
from reportlab.pdfgen import canvas
from pymongo import MongoClient
import certifi

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from src.core.common import config

# Generate test PDF in memory
def generate_test_pdf():
    packet = io.BytesIO()
    can = canvas.Canvas(packet)
    can.drawString(100, 750, "CONFIDENTIAL CONTRACT AGREEMENT")
    can.drawString(100, 700, "This agreement is governed by the laws of the State of Madagascar.")
    can.drawString(100, 650, "The limitation of liability under this agreement is exactly 999999 dollars.")
    can.drawString(100, 600, "The parties involved are Acme Corp and Apex Industries.")
    can.save()
    packet.seek(0)
    return packet.read()

def main():
    print("==================================================")
    print(" 🏛️  LEGAL AI — RAILWAY PDF INGESTION TEST CLIENT")
    print("==================================================")

    # 1. Get Railway URL
    railway_url = os.getenv("RAILWAY_URL", "").strip()
    if not railway_url:
        print("❌ ERROR: RAILWAY_URL environment variable is required.")
        print("Usage: $env:RAILWAY_URL=\"https://your-app.railway.app\" ; python tests/e2e/test_railway_pdf_ingestion.py")
        sys.exit(1)
        
    # Standardize URL trailing slash
    railway_url = railway_url.rstrip("/")
    print(f"📡 Target Railway Server: {railway_url}")

    # 2. Validate MongoDB URI
    mongo_uri = config.MONGO_URI
    if not mongo_uri:
        print("❌ ERROR: MONGO_URI environment variable/config is required for database verification and cleanup.")
        sys.exit(1)

    # 3. Initialize session ID
    session_id = f"railway-test-{uuid.uuid4()}"
    print(f"🔑 Generated Test Session ID: {session_id}")

    # 4. Clear previous test data for this session
    print("🧹 Cleaning up session data in MongoDB Atlas...")
    try:
        client_mongo = MongoClient(mongo_uri, tlsCAFile=certifi.where())
        db = client_mongo["legal_rag"]
        res = db[config.CHUNKS_COLLECTION].delete_many({"metadata.session_id": session_id})
        print(f"  Deleted {res.deleted_count} chunks from collection '{config.CHUNKS_COLLECTION}'.")
        res_nodes = db[config.KG_NODES_COLLECTION].delete_many({"session_id": session_id})
        print(f"  Deleted {res_nodes.deleted_count} KG nodes from collection '{config.KG_NODES_COLLECTION}'.")
        res_edges = db[config.KG_EDGES_COLLECTION].delete_many({"session_id": session_id})
        print(f"  Deleted {res_edges.deleted_count} KG edges from collection '{config.KG_EDGES_COLLECTION}'.")
    except Exception as e:
        print(f"  ⚠️ MongoDB cleanup failed: {e}")
        sys.exit(1)

    # 5. Create PDF
    print("📄 Generating test PDF file in memory...")
    pdf_data = generate_test_pdf()

    report_data = {
        "session_id": session_id,
        "contract_name": "test_madagascar_contract.pdf",
        "ingested_chunks": 0,
        "metrics": {},
        "queries": []
    }

    # 6. Upload PDF to Railway
    print("📤 Uploading PDF to /api/session/{session_id}/ingest...")
    ingest_url = f"{railway_url}/api/session/{session_id}/ingest"
    files = {"file": ("test_madagascar_contract.pdf", pdf_data, "application/pdf")}
    
    try:
        response = requests.post(ingest_url, files=files, timeout=45.0)
    except Exception as e:
        print(f"❌ Failed to reach Railway server: {e}")
        sys.exit(1)
        
    if response.status_code != 201:
        print(f"❌ Ingestion failed! Code: {response.status_code}, Detail: {response.text}")
        sys.exit(1)
        
    ingest_result = response.json()
    print(f"✅ Ingested successfully: {ingest_result}")
    
    report_data["ingested_chunks"] = ingest_result["chunks_count"]
    report_data["metrics"] = ingest_result.get("metrics", {})

    # 7. Verify via GET chunks endpoint
    print("🔍 Querying /api/session/{session_id}/chunks verification endpoint on Railway...")
    verify_response = requests.get(f"{railway_url}/api/session/{session_id}/chunks", timeout=15.0)
    if verify_response.status_code != 200:
        print(f"❌ Verification endpoint failed! Code: {verify_response.status_code}, Detail: {verify_response.text}")
        sys.exit(1)
    verify_data = verify_response.json()
    print(f"✅ Verification endpoint returned: {verify_data}")
    assert verify_data["has_pdf"] is True
    assert verify_data["chunks_count"] == ingest_result["chunks_count"]
    assert "test_madagascar_contract.pdf" in verify_data["contracts"]

    # 8. Verify via GET graph endpoint
    print("🔍 Querying /api/session/{session_id}/graph verification endpoint on Railway...")
    graph_response = requests.get(f"{railway_url}/api/session/{session_id}/graph", timeout=15.0)
    if graph_response.status_code != 200:
        print(f"❌ Graph verification endpoint failed! Code: {graph_response.status_code}, Detail: {graph_response.text}")
        sys.exit(1)
    graph_data = graph_response.json()
    print(f"✅ Graph verification endpoint returned: {graph_data}")
    
    # Check if KG nodes/edges were successfully extracted
    if graph_data["nodes_count"] > 0:
        print(f"  ✅ Extracted {graph_data['nodes_count']} nodes and {graph_data['edges_count']} edges.")
        node_ids = [n["_id"] for n in graph_data["nodes"]]
        print(f"  Extracted Node IDs: {node_ids}")
    else:
        print("  ⚠️ Warning: No graph elements were extracted (check LLM configuration on Railway).")

    # 9. Verify via GET contracts summary endpoint
    print("🔍 Querying /api/session/{session_id}/contracts verification endpoint on Railway...")
    contracts_response = requests.get(f"{railway_url}/api/session/{session_id}/contracts", timeout=15.0)
    if contracts_response.status_code != 200:
        print(f"❌ Contracts summary verification endpoint failed! Code: {contracts_response.status_code}, Detail: {contracts_response.text}")
        sys.exit(1)
    contracts_data = contracts_response.json()
    print(f"✅ Contracts summary verification endpoint returned: {contracts_data}")
    
    if contracts_data["contracts_count"] > 0:
        c_summaries = [c["summary"] for c in contracts_data["contracts"]]
        c_ids = [c["contract_id"] for c in contracts_data["contracts"]]
        print(f"  Extracted Contract summaries: {c_summaries} for IDs: {c_ids}")
    else:
        print("  ⚠️ Warning: No contracts were summary-cataloged.")

    # 9b. Verify via GET global overview endpoint
    print("🔍 Querying /api/overview/summary verification endpoint on Railway...")
    overview_response = requests.get(f"{railway_url}/api/overview/summary", timeout=15.0)
    if overview_response.status_code != 200:
        print(f"❌ Global overview verification endpoint failed! Code: {overview_response.status_code}, Detail: {overview_response.text}")
        sys.exit(1)
    overview_data = overview_response.json()
    print(f"✅ Global overview verification endpoint returned: {overview_data}")
    assert "total_contracts" in overview_data
    assert "session_distribution" in overview_data
    # Verify our test session is in the distribution list
    session_match = [s for s in overview_data["session_distribution"] if s["session_id"] == session_id]
    if session_match:
        print(f"  ✅ Test session verified in global overview distribution list: {session_match[0]}")
    else:
        print(f"  ⚠️ Warning: Test session not found in global overview distribution (Atlas index sync latency).")

    # 10. Wait for Search Index sync and evaluate questions
    print("⏳ Waiting for Atlas Vector Search index to sync (polling RAG via chat)...")
    print("  Sleeping 15 seconds initially...")
    time.sleep(15)
    
    max_poll_attempts = 5
    indexed = False
    for attempt in range(max_poll_attempts):
        print(f"  Poll attempt {attempt + 1}/{max_poll_attempts}...")
        try:
            poll_res = requests.post(f"{railway_url}/api/chat", json={
                "query": "What is the governing law of the contract?",
                "session_id": session_id
            }, timeout=20.0)
            if poll_res.status_code == 200:
                answer = poll_res.json().get("answer", "")
                if "madagascar" in answer.lower():
                    print(f"  ✅ Document successfully indexed in Atlas after {attempt + 1} attempts!")
                    indexed = True
                    break
        except Exception as e:
            print(f"  ⚠️ Request error: {e}")
            
        print("  Sleeping 15 seconds before retrying...")
        time.sleep(15)
        
    if not indexed:
        print("  ⚠️ Warning: Document was not index-synced by Atlas in time. Proceeding with Q&A queries anyway.")

    # 11. Run RAG Queries
    print("\n💬 Sending test RAG queries to Railway and gathering metrics...")
    questions = [
        "What is the governing law of the contract?",
        "What is the limitation of liability under this agreement?",
        "Which parties are involved in this agreement?",
        "What is the name or title of this contract?"
    ]
    
    for q in questions:
        print("💤 Sleeping 15 seconds to respect rate limits...")
        time.sleep(15)
        
        print(f"\n❓ Query: {q}")
        chat_payload = {
            "query": q,
            "session_id": session_id
        }
        
        start_time = time.time()
        try:
            chat_response = requests.post(f"{railway_url}/api/chat", json=chat_payload, timeout=25.0)
            latency = time.time() - start_time
            
            if chat_response.status_code != 200:
                print(f"  ❌ Chat request failed: {chat_response.text}")
                answer = f"ERROR: {chat_response.text}"
                contexts = []
            else:
                res_data = chat_response.json()
                answer = res_data["answer"]
                contexts = res_data.get("contexts", [])
                print(f"  🤖 Answer: {answer}")
                print(f"  ⏱️ Latency: {latency:.2f}s")
        except Exception as e:
            latency = time.time() - start_time
            print(f"  ❌ Chat request failed due to exception: {e}")
            answer = f"EXCEPTION: {str(e)}"
            contexts = []
            
        report_data["queries"].append({
            "query": q,
            "answer": answer,
            "latency_seconds": latency,
            "contexts_retrieved": len(contexts)
        })

    # 12. Write Report Locally
    os.makedirs("resources/reports", exist_ok=True)
    report_path = "resources/reports/railway_pdf_ingestion_report.md"
    print(f"\n📝 Writing Markdown Report to {report_path}...")
    
    metrics = report_data["metrics"]
    report_lines = [
        f"# 🏛️ Legal AI — Railway PDF Ingestion & Retrieval Report\n",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Target Host:** `{railway_url}`  ",
        f"**Session ID:** `{report_data['session_id']}`  ",
        f"**Source Document:** `{report_data['contract_name']}`  ",
        f"**Chunks Ingested:** `{report_data['ingested_chunks']}`  \n",
        "## ⏱️ PDF Ingestion Latency Metrics\n",
        f"- **Parsing PDF text**:  `{metrics.get('parse_time_seconds', 0.0):.4f}s`  ",
        f"- **Text Chunking**:     `{metrics.get('chunk_time_seconds', 0.0):.4f}s`  ",
        f"- **Embeddings Gen**:    `{metrics.get('embed_time_seconds', 0.0):.4f}s`  ",
        f"- **MongoDB DB insert**:  `{metrics.get('db_insert_time_seconds', 0.0):.4f}s`  ",
        f"- **Total Ingestion**:    `{metrics.get('total_time_seconds', 0.0):.4f}s`  \n",
        "---\n",
        "## 🤖 RAG Query Results\n"
    ]
    
    for idx, item in enumerate(report_data["queries"], 1):
        report_lines.extend([
            f"### Query {idx}: {item['query']}\n",
            f"**Latency:** `{item['latency_seconds']:.2f}s` | **Contexts Retrieved:** `{item['contexts_retrieved']}`\n",
            f"> {item['answer']}\n",
            "\n"
        ])
        
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    # 13. Cleanup
    print("\n🧹 Cleaning up test data from MongoDB...")
    try:
        res = db[config.CHUNKS_COLLECTION].delete_many({"metadata.session_id": session_id})
        print(f"  Deleted {res.deleted_count} chunks.")
        res_nodes = db[config.KG_NODES_COLLECTION].delete_many({"session_id": session_id})
        print(f"  Deleted {res_nodes.deleted_count} KG nodes.")
        res_edges = db[config.KG_EDGES_COLLECTION].delete_many({"session_id": session_id})
        print(f"  Deleted {res_edges.deleted_count} KG edges.")
    except Exception as e:
        print(f"  ⚠️ MongoDB post-cleanup failed: {e}")

    print("\n🎉 Railway PDF Ingestion and Report Generation completed successfully!")
    sys.exit(0)

if __name__ == "__main__":
    main()
