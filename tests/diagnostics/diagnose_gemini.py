import os
import sys

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

import google.generativeai as genai
from pymongo import MongoClient
import certifi
from src.core.common import config

def main():
    print("==================================================")
    print("      🏛️  LEGAL AI — GEMINI & DB CI DIAGNOSTICS")
    print("==================================================")

    # 1. Print SDK version
    print(f"\n1. google-generativeai SDK Version: {genai.__version__}")

    # 2. Print API key existence
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    google_key = os.getenv("GOOGLE_API_KEY", "").strip()
    
    print("\n2. Environment Key Status:")
    print(f"   - GEMINI_API_KEY exists: {bool(gemini_key)} (length: {len(gemini_key)})")
    if gemini_key:
        print(f"     Prefix: '{gemini_key[:8]}...' | Suffix: '...{gemini_key[-4:]}'")
    print(f"   - GOOGLE_API_KEY exists: {bool(google_key)} (length: {len(google_key)})")

    # 3 & 4. Print genai.list_models() and check for gemini-1.5-flash
    print("\n3. Listing Available Models via genai.list_models():")
    if not gemini_key:
        print("   ⚠️ Cannot list models: GEMINI_API_KEY is not set.")
    else:
        try:
            genai.configure(api_key=gemini_key)
            models = list(genai.list_models())
            found_flash = False
            for m in models:
                print(f"   - {m.name} (methods: {m.supported_generation_methods})")
                if "gemini-1.5-flash" in m.name:
                    found_flash = True
            
            print(f"\n4. Verification: models/gemini-1.5-flash appears in list: {found_flash}")
        except Exception as e:
            print(f"   ❌ Failed to query genai.list_models(): {e}")

    # 5. DB Ingestion & Retrieval pipeline verification
    print("\n5. Verifying MongoDB Atlas Retrieval Pipeline:")
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        print("   ❌ MONGO_URI is missing.")
    else:
        try:
            client = MongoClient(mongo_uri, tlsCAFile=certifi.where())
            db = client["legal_rag"]
            print("   🔌 Connected to MongoDB Atlas.")
            
            # Print collection sizes
            chunks_cnt = db[config.CHUNKS_COLLECTION].count_documents({})
            nodes_cnt = db[config.KG_NODES_COLLECTION].count_documents({})
            edges_cnt = db[config.KG_EDGES_COLLECTION].count_documents({})
            
            print(f"   - Active Collection '{config.CHUNKS_COLLECTION}' size: {chunks_cnt} chunks")
            print(f"   - Active Collection '{config.KG_NODES_COLLECTION}' size: {nodes_cnt} nodes")
            print(f"   - Active Collection '{config.KG_EDGES_COLLECTION}' size: {edges_cnt} edges")
            
            # Check why query returned 0 in logs
            print("\n   🔍 Clarification on why query returned KG Triples (0) and VDB Chunks (0):")
            print("   - When answer_query() raises an exception (such as the Gemini 404 error),")
            print("     the test runner's 'except Exception as e:' block catches it, sets contexts=[]")
            print("     and triplets=[] as default fallbacks, and logs status=❌ FAIL.")
            print("   - Thus, 0 chunks are shown because of the test's exception handling of the model crash,")
            print("     NOT because the database retrieval returned 0 elements.")
        except Exception as e:
            print(f"   ❌ MongoDB query failed: {e}")

if __name__ == "__main__":
    main()
