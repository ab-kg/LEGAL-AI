import os
import sys
from pymongo import MongoClient
import certifi

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.core.common import config

def main():
    print("==================================================")
    print("    LEGAL AI - TEST DATABASE INITIALIZATION")
    print("==================================================")

    # 1. Connect to MongoDB
    mongo_uri = getattr(config, "MONGO_URI", None) or os.getenv("MONGO_URI", "")
    mongo_uri = mongo_uri.strip() if mongo_uri else ""

    if not mongo_uri:
        print("❌ ERROR: MONGO_URI is not configured in config.py or environment variables.")
        sys.exit(1)

    print("🔌 Connecting to MongoDB Atlas...")
    try:
        client = MongoClient(mongo_uri, tlsCAFile=certifi.where())
        db = client["legal_rag"]
        print("✅ Connected successfully to 'legal_rag' database.")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)

    # 2. Setup collections
    test_collections = ["chunks_test", "kg_nodes_test", "kg_edges_test"]
    print("\n📂 Initializing collections...")
    
    existing_collections = db.list_collection_names()
    for col_name in test_collections:
        if col_name in existing_collections:
            print(f"  • Collection '{col_name}' already exists.")
        else:
            try:
                db.create_collection(col_name)
                print(f"  • Created collection '{col_name}'.")
            except Exception as e:
                print(f"  • Warning creating '{col_name}': {e}")

    # 3. Create Standard Indexes for KG Test Collections
    print("\n📊 Creating standard indexes on graph test collections...")
    try:
        edges_col = db["kg_edges_test"]
        edges_col.create_index("source")
        edges_col.create_index("target")
        edges_col.create_index("source_chunks")
        edges_col.create_index("label")
        print("  ✅ Standard indexes created for 'kg_edges_test'.")
    except Exception as e:
        print(f"  ❌ Failed to create standard indexes: {e}")

    # 4. Attempt Vector Search Index Creation on chunks_test
    print("\n🧠 Setting up Vector Search Index on 'chunks_test'...")
    chunks_test_col = db["chunks_test"]
    
    # Check if Search Indexes can be listed or created via PyMongo
    try:
        # Check if index already exists
        existing_search_indexes = list(chunks_test_col.list_search_indexes())
        vector_index_exists = any(idx.get("name") == "vector_index" for idx in existing_search_indexes)
        
        if vector_index_exists:
            print("  ✅ Vector Search Index 'vector_index' already exists on 'chunks_test'.")
        else:
            print("  ⚙️ Registering 'vector_index' search index on 'chunks_test'...")
            
            # Definition for the modern Atlas Vector Search index
            index_model = {
                "definition": {
                    "fields": [
                        {
                            "type": "vector",
                            "path": "embedding",
                            "numDimensions": 384,
                            "similarity": "cosine"
                        }
                    ]
                },
                "name": "vector_index",
                "type": "vectorSearch"
            }
            
            # Create index using the driver helper
            chunks_test_col.create_search_index(model=index_model)
            print("  ✅ Vector Search Index registration requested successfully!")
            print("  ℹ️ MongoDB Atlas will take 1-3 minutes to build the index in the background.")
            
    except Exception as e:
        print(f"  ⚠️ Automatic search index creation skipped or failed: {e}")
        print("\n📝 MANUAL INSTRUCTIONS:")
        print("Please create the Vector Search index manually via the MongoDB Atlas GUI:")
        print("  1. Go to Atlas Web Portal -> Search -> Create Search Index.")
        print("  2. Select 'JSON Editor' under 'Atlas Vector Search'.")
        print("  3. Set database name to 'legal_rag' and collection name to 'chunks_test'.")
        print("  4. Set Index Name to: 'vector_index'.")
        print("  5. Paste this JSON index definition:")
        print("     {")
        print("       \"fields\": [")
        print("         {")
        print("           \"type\": \"vector\",")
        print("           \"path\": \"embedding\",")
        print("           \"numDimensions\": 384,")
        print("           \"similarity\": \"cosine\"")
        print("         }")
        print("       ]")
        print("     }")
        print("  6. Click Next and click 'Create Vector Search Index'.")

    print("\n🏁 Initialization complete!")

if __name__ == "__main__":
    main()
