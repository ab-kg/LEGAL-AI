import os
import sys
import io
import time
import uuid
from datetime import datetime

# 1. Force the test database collection namespace
os.environ["CHUNKS_COLLECTION"] = "chunks_test"
os.environ["KG_NODES_COLLECTION"] = "kg_nodes_test"
os.environ["KG_EDGES_COLLECTION"] = "kg_edges_test"

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from fastapi.testclient import TestClient
from pymongo import MongoClient
import certifi
from reportlab.pdfgen import canvas

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
    print(" 🏛️  LEGAL AI — PDF INGESTION & REPORT GENERATOR")
    print("==================================================")

    # Validate Environment
    mongo_uri = config.MONGO_URI
    provider = config.LLM_PROVIDER
    
    if provider == "gemini":
        key = config.GEMINI_API_KEY
        key_name = "GEMINI_API_KEY"
    else:
        key = config.GROQ_API_KEY
        key_name = "GROQ_API_KEY"
        
    if not mongo_uri or not key:
        print(f"❌ ERROR: MONGO_URI and {key_name} environment variables are required for provider '{provider}'.")
        sys.exit(1)

    # Initialize session ID
    session_id = f"test-session-{uuid.uuid4()}"
    print(f"🔑 Using Session ID: {session_id}")

    # Clear previous test data for this session
    print("🧹 Cleaning up chunks in test collection...")
    try:
        client_mongo = MongoClient(mongo_uri, tlsCAFile=certifi.where())
        db = client_mongo["legal_rag"]
        res = db[config.CHUNKS_COLLECTION].delete_many({"metadata.session_id": session_id})
        print(f"  Deleted {res.deleted_count} chunks matching session ID.")
        res_nodes = db[config.KG_NODES_COLLECTION].delete_many({"session_id": session_id})
        print(f"  Deleted {res_nodes.deleted_count} KG nodes matching session ID.")
        res_edges = db[config.KG_EDGES_COLLECTION].delete_many({"session_id": session_id})
        print(f"  Deleted {res_edges.deleted_count} KG edges matching session ID.")
    except Exception as e:
        print(f"  ⚠️ MongoDB cleanup failed: {e}")
        sys.exit(1)

    # Create PDF
    print("📄 Generating test PDF file in memory...")
    pdf_data = generate_test_pdf()

    # Import app
    from src.app import app
    
    report_data = {
        "session_id": session_id,
        "contract_name": "test_madagascar_contract.pdf",
        "ingested_chunks": 0,
        "metrics": {},
        "queries": []
    }

    # Enter lifespan scope to boot RAG engine
    print("🚀 Starting FastAPI TestClient...")
    with TestClient(app) as client:
        # 1. Ingest PDF
        print("📤 Uploading PDF to /api/session/{session_id}/ingest...")
        ingest_url = f"/api/session/{session_id}/ingest"
        
        files = {"file": ("test_madagascar_contract.pdf", pdf_data, "application/pdf")}
        response = client.post(ingest_url, files=files)
        
        if response.status_code != 201:
            print(f"❌ Ingestion failed! Code: {response.status_code}, Detail: {response.text}")
            sys.exit(1)
            
        ingest_result = response.json()
        print(f"✅ Ingested successfully: {ingest_result}")
        
        report_data["ingested_chunks"] = ingest_result["chunks_count"]
        report_data["metrics"] = ingest_result.get("metrics", {})
        
        # 1b. Verify via GET endpoint
        print("🔍 Querying /api/session/{session_id}/chunks verification endpoint...")
        verify_response = client.get(f"/api/session/{session_id}/chunks")
        if verify_response.status_code != 200:
            print(f"❌ Verification endpoint failed! Code: {verify_response.status_code}, Detail: {verify_response.text}")
            sys.exit(1)
        verify_data = verify_response.json()
        print(f"✅ Verification endpoint returned: {verify_data}")
        assert verify_data["has_pdf"] is True
        assert verify_data["chunks_count"] == ingest_result["chunks_count"]
        assert "test_madagascar_contract.pdf" in verify_data["contracts"]
        
        # 1c. Verify dynamic KG extraction
        print("🔍 Querying /api/session/{session_id}/graph verification endpoint...")
        graph_response = client.get(f"/api/session/{session_id}/graph")
        if graph_response.status_code != 200:
            print(f"❌ Graph verification endpoint failed! Code: {graph_response.status_code}, Detail: {graph_response.text}")
            sys.exit(1)
        graph_data = graph_response.json()
        print(f"✅ Graph verification endpoint returned: {graph_data}")
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            assert graph_data["nodes_count"] > 0
            assert graph_data["edges_count"] > 0
            node_ids = [n["_id"] for n in graph_data["nodes"]]
            print(f"  Extracted Node IDs: {node_ids}")
            
        # 1d. Verify contract summary retrieval
        print("🔍 Querying /api/session/{session_id}/contracts verification endpoint...")
        contracts_response = client.get(f"/api/session/{session_id}/contracts")
        if contracts_response.status_code != 200:
            print(f"❌ Contracts summary verification endpoint failed! Code: {contracts_response.status_code}, Detail: {contracts_response.text}")
            sys.exit(1)
        contracts_data = contracts_response.json()
        print(f"✅ Contracts summary verification endpoint returned: {contracts_data}")
        if gemini_key:
            assert contracts_data["contracts_count"] > 0
            c_summaries = [c["summary"] for c in contracts_data["contracts"]]
            c_ids = [c["contract_id"] for c in contracts_data["contracts"]]
            print(f"  Extracted Contract summaries: {c_summaries} for IDs: {c_ids}")
            assert "test_madagascar_contract.pdf" in c_ids
        
        # Check DB to verify documents exist
        print("🔍 Verifying chunks in MongoDB chunks_test collection...")
        db_chunks = list(db[config.CHUNKS_COLLECTION].find({"metadata.session_id": session_id}))
        print(f"  Found {len(db_chunks)} chunks in test DB collection '{config.CHUNKS_COLLECTION}'.")

        # 2. Write a minimal Markdown Report (required by CI workflow artifacts upload)
        os.makedirs("resources/reports", exist_ok=True)
        report_path = "resources/reports/pdf_ingestion_report.md"
        print(f"\n📝 Writing Markdown Report to {report_path}...")
        
        metrics = report_data["metrics"]
        report_lines = [
            f"# 🏛️ Legal AI — PDF Ingestion Test Report (CI Streamlined)\n",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
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
            "## 🔍 Verification Status\n",
            f"- [x] Chunks Ingested & Stored in VDB: **{verify_data['chunks_count']}** chunks verified.",
            f"- [x] Knowledge Graph Nodes & Edges: **{graph_data.get('nodes_count', 0)} nodes / {graph_data.get('edges_count', 0)} edges** extracted.",
            f"- [x] Contract Summaries cataloged: **{contracts_data.get('contracts_count', 0)}** contracts verified.\n"
        ]
        
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
            
    # 3. Post-cleanup
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
        
    print("\n🎉 PDF Ingestion and Report Generation completed successfully!")
    sys.exit(0)

if __name__ == "__main__":
    main()
