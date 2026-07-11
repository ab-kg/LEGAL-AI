"""
Database Connection
====================
Thin wrappers for MongoDB Atlas connectivity.
"""

from pymongo import MongoClient
import certifi

from src.core.common import config


def get_mongo_client(uri=None):
    """
    Create a MongoClient connected to MongoDB Atlas with TLS.

    Args:
        uri: MongoDB connection string.  Defaults to ``config.MONGO_URI``.

    Returns:
        A ``MongoClient`` instance, or ``None`` if *uri* is empty.
    """
    uri = uri or config.MONGO_URI
    if not uri:
        return None
    return MongoClient(uri, tlsCAFile=certifi.where())


def get_database(client, name="legal_rag"):
    """Return the named database from an existing MongoClient."""
    if client is None:
        return None
    return client[name]


def ping(db):
    """
    Verify database reachability by listing collections.

    Returns True on success, False on failure.
    """
    if db is None:
        return False
    try:
        db.list_collection_names()
        return True
    except Exception:
        return False
