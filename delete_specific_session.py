import os
import sys

# Add the src directory to path so we can import config
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from pymongo import MongoClient
import core.common.config as config

print("Connecting to MongoDB...")

client = MongoClient(config.MONGO_URI)
db = client[config.MONGO_DB_NAME]

print("Searching for session starting with '1cad946f'...")
# Find the exact session ID

session = db[config.CHAT_SESSIONS_COLLECTION].find_one({"_id": {"$regex": "^1cad946f"}})


if session:
    session_id = session["_id"]
    print(f"Found session: {session_id}")
    
    # Delete from chat_sessions
    res1 = db[config.CHAT_SESSIONS_COLLECTION].delete_one({"_id": session_id})
    print(f"Deleted from chat_sessions: {res1.deleted_count}")
    
    # Delete from chunks
    res2 = db[config.CHUNKS_COLLECTION].delete_many({"metadata.session_id": session_id})
    print(f"Deleted from chunks: {res2.deleted_count}")
    
    # Delete from kg_nodes
    res3 = db[config.KG_NODES_COLLECTION].delete_many({"session_id": session_id})
    print(f"Deleted from kg_nodes: {res3.deleted_count}")
    
    # Delete from kg_edges
    res4 = db[config.KG_EDGES_COLLECTION].delete_many({"session_id": session_id})
    print(f"Deleted from kg_edges: {res4.deleted_count}")
    
    print("Deletion complete!")
else:
    print("Could not find a session starting with '1cad946f'. Trying to delete it from chunks directly...")
    
    # Maybe the session was already deleted from chat_sessions but orphaned chunks remain?
    res2 = db[config.CHUNKS_COLLECTION].delete_many({"metadata.session_id": {"$regex": "^1cad946f"}})
    res3 = db[config.KG_NODES_COLLECTION].delete_many({"session_id": {"$regex": "^1cad946f"}})
    res4 = db[config.KG_EDGES_COLLECTION].delete_many({"session_id": {"$regex": "^1cad946f"}})    
    print(f"Deleted orphaned chunks: {res2.deleted_count}")
    print(f"Deleted orphaned kg_nodes: {res3.deleted_count}")
    print(f"Deleted orphaned kg_edges: {res4.deleted_count}")
    print("Done!")
