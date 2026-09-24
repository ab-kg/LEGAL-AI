"""
Knowledge Graph Builder
========================
Batch-constructs the Knowledge Graph from ``contract_data.json`` and
uploads to MongoDB Atlas.  Also provides shared helpers for dynamic
(per-PDF) graph insertion.
"""

import json
import os

import networkx as nx

from src.core.common import config
from src.core.common.utils import safe_str, make_location_id
from src.core.common import db as db_module

# ──────────────────────────────────────────────────────────────────
#  Shared: Build graph elements from a single contract dict
# ──────────────────────────────────────────────────────────────────

def build_graph_elements(contract_id, data, session_id=None):
    """
    Convert a contract data dict into lists of node and edge dicts
    suitable for MongoDB insertion.

    Returns:
        tuple: (nodes_list, edges_list)
    """
    nodes = []
    edges = []

    # A. Contract Node
    nodes.append({
        "_id": contract_id,
        "entity_type": "Contract",
        "session_id": session_id,
        "summary": safe_str(data.get("summary")),
        "contract_type": safe_str(data.get("contract_type")),
        "effective_date": safe_str(data.get("effective_date")),
        "contract_scope": safe_str(data.get("contract_scope")),
        "duration": safe_str(data.get("duration")),
        "end_date": safe_str(data.get("end_date")),
        "total_amount": safe_str(data.get("total_amount")),
    })

    # B. Governing Law Location
    gov_law = data.get("governing_law")
    if gov_law and isinstance(gov_law, dict):
        gov_law_id = make_location_id(gov_law)
        if gov_law_id:
            nodes.append({
                "_id": gov_law_id,
                "entity_type": "Location",
                "session_id": session_id,
                "address": safe_str(gov_law.get("address")),
                "city": safe_str(gov_law.get("city")),
                "state": safe_str(gov_law.get("state")),
                "country": safe_str(gov_law.get("country")),
            })
            edges.append({
                "source": contract_id,
                "target": gov_law_id,
                "label": "HAS_GOVERNING_LAW",
                "source_chunks": [contract_id],
                "session_id": session_id,
            })

    # C. Party Nodes & Edges
    for party in data.get("parties") or []:
        party_name = party.get("name")
        if not party_name:
            continue
        nodes.append({
            "_id": party_name,
            "entity_type": "Party",
            "session_id": session_id,
        })
        edges.append({
            "source": party_name,
            "target": contract_id,
            "label": "PARTY_TO",
            "role": safe_str(party.get("role", "Party")),
            "source_chunks": [contract_id],
            "session_id": session_id,
        })

        # Party Location
        p_loc = party.get("location")
        if p_loc and isinstance(p_loc, dict):
            p_loc_id = make_location_id(p_loc)
            if p_loc_id:
                nodes.append({
                    "_id": p_loc_id,
                    "entity_type": "Location",
                    "session_id": session_id,
                    "address": safe_str(p_loc.get("address")),
                    "city": safe_str(p_loc.get("city")),
                    "state": safe_str(p_loc.get("state")),
                    "country": safe_str(p_loc.get("country")),
                })
                edges.append({
                    "source": party_name,
                    "target": p_loc_id,
                    "label": "HAS_LOCATION",
                    "source_chunks": [contract_id],
                    "session_id": session_id,
                })

    # D. Clause Nodes & Edges
    for clause in data.get("clauses") or []:
        clause_type = clause.get("clause_type")
        if not clause_type:
            continue
        clause_id = f"Clause_{contract_id}_{clause_type}"
        nodes.append({
            "_id": clause_id,
            "entity_type": "Clause",
            "session_id": session_id,
            "clause_type": safe_str(clause_type),
            "summary": safe_str(clause.get("summary")),
        })
        edges.append({
            "source": contract_id,
            "target": clause_id,
            "label": "HAS_CLAUSE",
            "source_chunks": [contract_id],
            "session_id": session_id,
        })
    return nodes, edges

def upsert_graph_data(db, contract_id, data, session_id):
    """
    Extract graph elements and upsert them into MongoDB Atlas.

    Uses ``replace_one(upsert=True)`` so repeated ingestion of the same
    contract is idempotent.
    """
    if db is None:
        return
    nodes, edges = build_graph_elements(contract_id, data, session_id)
    for node in nodes:
        db[config.KG_NODES_COLLECTION].replace_one(
            {"_id": node["_id"]}, node, upsert=True
        )
    for edge in edges:
        db[config.KG_EDGES_COLLECTION].replace_one(
            {"source": edge["source"], "target": edge["target"], "label": edge["label"]},
            edge,
            upsert=True,
        )
        
# ──────────────────────────────────────────────────────────────────
#  Batch Pipeline (from contract_data.json)
# ──────────────────────────────────────────────────────────────────

def build_infrastructure():
    """
    Generator that builds the full Knowledge Graph from
    ``contract_data.json`` and uploads to MongoDB Atlas.

    Yields progress dicts: ``{"status": "progress", "message": "..."}``.
    """
    yield {"status": "progress", "message": "🚀 Starting Knowledge Graph indexing from contract_data.json..."}

    G = nx.DiGraph()

    # ── Locate contract_data.json ────────────────────────────────
    contract_data_path = os.path.join("resources", "research", "import-graph", "contract_data.json")
    if not os.path.exists(contract_data_path):
        # Fallback to module-relative path if executed from another working directory
        contract_data_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "resources", "research", "import-graph", "contract_data.json")
        )
    
    if not os.path.exists(contract_data_path):
        msg = "Could not find contract_data.json (tried CWD and __file__ relative paths)"
        print(f"❌ {msg}", flush=True)
        raise FileNotFoundError(msg)

    yield {"status": "progress", "message": "📖 Loading contract_data.json..."}
    print(f"📖 Loading {contract_data_path} ...", flush=True)
    with open(contract_data_path, "r", encoding="utf-8") as f:
        contracts = json.load(f)

    total = len(contracts)
    print(f"📊 Loaded {total} contracts. Building graph...", flush=True)
    yield {"status": "progress", "message": f"📊 Loaded {total} contracts. Reconstructing graph elements..."}

    skipped = 0
    for idx, contract in enumerate(contracts):
        contract_id = contract.get("file_id")
        if not contract_id:
            skipped += 1
            continue

        if (idx + 1) % 100 == 0 or idx == total - 1:
            print(f"  Processing contract {idx + 1}/{total}...", flush=True)

        # Build elements using the shared function (session_id=None for bulk)
        nodes, edges = build_graph_elements(contract_id, contract, session_id=None)

        # Add to NetworkX graph
        for node in nodes:
            node_id = node.pop("_id")
            node.pop("session_id", None)  # Not needed for local graph
            G.add_node(node_id, **node)

        for edge in edges:
            e = dict(edge)
            e.pop("session_id", None)
            G.add_edge(e.pop("source"), e.pop("target"), **e)

    if skipped:
        print(f"⚠️ Skipped {skipped} contracts with missing file_id.", flush=True)

    print(f"✅ Graph built: {G.number_of_nodes()} nodes | {G.number_of_edges()} edges", flush=True)

    # ── Save local JSON fallback ─────────────────────────────────
    try:
        with open(config.GRAPH_PATH, "w", encoding="utf-8") as f:
            json.dump(nx.node_link_data(G), f, indent=2)
        print(f"💾 Local fallback saved to {config.GRAPH_PATH}", flush=True)
    except Exception as e:
        print(f"⚠️ Could not save local fallback: {e}", flush=True)

    # ── Upload to MongoDB Atlas ──────────────────────────────────
    mongo_uri = getattr(config, "MONGO_URI", None) or os.getenv("MONGO_URI", "")
    mongo_uri = mongo_uri.strip() if mongo_uri else ""

    if not mongo_uri:
        print("⚠️ MONGO_URI not set — Knowledge Graph stored locally only.", flush=True )
        yield {"status": "progress", "message": "⚠️ MONGO_URI not set. Local-only mode."}
    else:
        try:
            print("💾 Connecting to MongoDB Atlas...", flush=True)
            yield {"status": "progress", "message": "💾 Uploading Knowledge Graph to MongoDB Atlas..."}
            client = db_module.get_mongo_client(mongo_uri)
            db = db_module.get_database(client)

            # Drop old collections
            db[config.KG_NODES_COLLECTION].drop()
            db[config.KG_EDGES_COLLECTION].drop()

            # Format nodes and edges from the NetworkX graph
            nodes_list = []
            for node, data in G.nodes(data=True):
                doc = {"_id": node}
                doc.update(data)
                nodes_list.append(doc)

            edges_list = []
            for u, v, data in G.edges(data=True):
                doc = {"source": u, "target": v, "label": data.get("label"), "source_chunks": data.get("source_chunks", [])}
                for k, val in data.items():
                    if k not in ("label", "source_chunks"):
                        doc[k] = val
                edges_list.append(doc)

            # Batched insert
            BATCH = 5000
            if nodes_list:
                for i in range(0, len(nodes_list), BATCH):
                    batch = nodes_list[i : i + BATCH]
                    db[config.KG_NODES_COLLECTION].insert_many(batch, ordered=False)
                    print(f"  Inserted nodes batch {i // BATCH + 1} ({len(batch)} docs)", flush=True)

            if edges_list:
                for i in range(0, len(edges_list), BATCH):
                    batch = edges_list[i : i + BATCH]
                    db[config.KG_EDGES_COLLECTION].insert_many(batch, ordered=False)
                    print(f"  Inserted edges batch {i // BATCH + 1} ({len(batch)} docs)", flush=True)

            # Build indexes
            db[config.KG_EDGES_COLLECTION].create_index("source")
            db[config.KG_EDGES_COLLECTION].create_index("target")
            db[config.KG_EDGES_COLLECTION].create_index("source_chunks")
            db[config.KG_EDGES_COLLECTION].create_index("label")

            print(f"✅ MongoDB Atlas indexed! Nodes: {len(nodes_list)} | Edges: {len(edges_list)}", flush=True)
            yield {"status": "progress", "message": f"✅ Atlas indexed! Nodes: {len(nodes_list)} | Edges: {len(edges_list)}"}
        except Exception as e:
            print(f"❌ MongoDB Atlas upload failed: {e}", flush=True)
            yield {"status": "progress", "message": f"❌ Atlas upload failed: {e}"}

    print(f"\n✅ Indexing Complete! Nodes: {G.number_of_nodes()} | Edges: {G.number_of_edges()}", flush=True)
    yield {"status": "progress", "message": f"✅ Indexing Complete! Nodes: {G.number_of_nodes()} | Edges: {G.number_of_edges()}"}


if __name__ == "__main__":
    for step in build_infrastructure():
        pass
