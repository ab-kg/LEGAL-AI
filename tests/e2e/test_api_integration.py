import os
import sys
import time
import threading
import requests
import uvicorn

# Add parent directory to path to ensure modules can be loaded.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# IPv4 patch applied via conftest.py
from src.core.common.utils import force_ipv4
force_ipv4()
from src.core.common import config
from src.core.rag_pipeline import LegalGraphRAG
import src.app as app_module

def run_server():
    """Starts the FastAPI app using Uvicorn."""
    print("🤖 Starting Uvicorn test server...")
    uvicorn.run(app_module.app, host="127.0.0.1", port=8000, log_level="warning")

def main():
    print("==================================================")
    print(" 🏛️  LEGAL AI — API SERVER INTEGRATION TEST  🏛️")
    print("==================================================")

    # --- 1. Validate Env Credentials ---
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

    # --- 2. Initialize and Inject RAG Engine ---
    print("🧠 Booting LegalGraphRAG Engine using existing Atlas DB...")
    try:
        # Pre-initialize the engine directly
        rag_engine = LegalGraphRAG()
        # Inject the initialized engine into the app module's global namespace
        app_module.engine = rag_engine
        print("✅ Engine successfully injected into app.py!")
    except Exception as e:
        print(f"❌ Failed to initialize RAG Engine: {e}")
        sys.exit(1)

    # --- 3. Start Server in a Background Thread ---
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Wait for server to become responsive
    url = "http://127.0.0.1:8000/api/session"
    max_retries = 10
    server_ready = False
    
    print("⏳ Waiting for API server to become online...")
    for i in range(max_retries):
        try:
            response = requests.post(url, json={}, timeout=2.0)
            if response.status_code == 200:
                server_ready = True
                print("✅ API Server is online and responsive!")
                break
        except requests.exceptions.ConnectionError:
            time.sleep(1.0)
            
    if not server_ready:
        print("❌ ERROR: API server failed to start within 10 seconds.")
        sys.exit(1)

    # --- 4. Run Chat Query Integration Test ---
    print("\n💬 Sending test RAG query to '/api/chat'...")
    chat_url = "http://127.0.0.1:8000/api/chat"
    payload = {
        "query": "what is breach of contract"
    }

    try:
        start_time = time.time()
        chat_response = requests.post(chat_url, json=payload, timeout=15.0)
        latency = time.time() - start_time
        
        if chat_response.status_code != 200:
            print(f"❌ FAILED: API returned status code {chat_response.status_code}")
            print(f"Response: {chat_response.text}")
            sys.exit(1)
            
        data = chat_response.json()
        print(f"✅ SUCCESS: Received HTTP 200 in {latency:.2f} seconds!")
        
        # Validate response schema
        assert "answer" in data, "Response missing 'answer' key"
        assert "contexts" in data, "Response missing 'contexts' key"
        assert len(data["contexts"]) > 0, "No semantic contexts returned in search"
        
        print("\n" + "="*60)
        print("🤖 [FASTAPI RAG RESPONSE]")
        print(f"Answer: {data['answer'][:250]}...")
        print("="*60 + "\n")
        
        # --- 5. Run Global Overview Test ---
        print("\n📊 Sending test query to '/api/overview/summary'...")
        overview_url = "http://127.0.0.1:8000/api/overview/summary"
        overview_response = requests.get(overview_url, timeout=10.0)
        if overview_response.status_code != 200:
            print(f"❌ FAILED: Overview API returned status code {overview_response.status_code}")
            sys.exit(1)
        overview_data = overview_response.json()
        assert "total_contracts" in overview_data, "Overview missing 'total_contracts' key"
        assert "session_distribution" in overview_data, "Overview missing 'session_distribution' key"
        print(f"✅ SUCCESS: Overview returned: {overview_data}")
        
        print("🎉 All API Integration Tests Passed Successfully!")
        sys.exit(0)
        
    except AssertionError as e:
        print(f"❌ SCHEMA VALIDATION FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ TEST RUN FAILED: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
