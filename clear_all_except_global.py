import os

from dotenv import load_dotenv

from pymongo import MongoClient
import certifi

load_dotenv()
uri = os.getenv("MONGO_URI", "").strip()

if not uri:
    print("MONGO_URI not found in .env")
    exit(1)

client = MongoClient(uri, tlsCAFile=certifi.where())
db = client["legal_rag"]

# Delete chat sessions
res = db["chat_sessions"].delete_many({"_id": {"$ne": "global"}})
print(f"Deleted {res.deleted_count} non-global chat sessions.")

# Delete chunks
res = db["chunks"].delete_many({"metadata.session_id": {"$nin": ["global", None]}})
print(f"Deleted {res.deleted_count} non-global chunks.")

# Delete kg_nodes
res = db["kg_nodes"].delete_many({"session_id": {"$nin": ["global", None]}})
print(f"Deleted {res.deleted_count} non-global KG nodes.")

# Delete kg_edges
res = db["kg_edges"].delete_many({"session_id": {"$nin": ["global", None]}})
print(f"Deleted {res.deleted_count} non-global KG edges.")

print("Cleanup complete!")
