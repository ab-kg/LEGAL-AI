"""
Retrieval Module
=================
Hybrid retrieval: MongoDB Atlas Vector Search + Knowledge Graph triple
matching + context synthesis.
"""

from src.core.common import config


# ────────────────────────────────────────────────────────────────────
#  1. Semantic Vector Search (MongoDB Atlas $vectorSearch)
# ────────────────────────────────────────────────────────────────────

def vector_search(db, query_embedding, session_id=None):
    """
    Run a vector similarity search against the chunks collection.

    Returns:
        tuple: (retrieved_texts, retrieved_chunk_ids, retrieved_contract_ids,
                chunks_by_contract)
    """
    retrieved_texts = []
    retrieved_chunk_ids = set()
    retrieved_contract_ids = set()
    chunks_by_contract = {}

    if db is None:
        return retrieved_texts, retrieved_chunk_ids, retrieved_contract_ids, chunks_by_contract

    try:
        results = []
        
        # 1. If in a session, fetch ALL chunks for the session directly (bypasses index sync delay!)
        if session_id:
            session_chunks = list(db[config.CHUNKS_COLLECTION].find({"metadata.session_id": session_id}))
            if session_chunks:
                # Score them in memory using dot product
                for chunk in session_chunks:
                    chunk_vec = chunk.get("embedding", [])
                    if chunk_vec and len(chunk_vec) == len(query_embedding):
                        score = sum(a * b for a, b in zip(query_embedding, chunk_vec))
                        chunk["score"] = score
                    else:
                        chunk["score"] = -1
                
                # Sort descending by score and take top 3
                session_chunks.sort(key=lambda x: x.get("score", -1), reverse=True)
                results = session_chunks[:3]

        # 2. If no session chunks found, fall back to global $vectorSearch
        if not results:
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": "vector_index",
                        "path": "embedding",
                        "queryVector": query_embedding,
                        "numCandidates": 100,
                        "limit": 3,
                    }
                },
                {
                    "$project": {
                        "text": 1,
                        "metadata": 1,
                        "score": {"$meta": "vectorSearchScore"},
                    }
                },
                {
                    "$match": {
                        "$or": [
                            {"metadata.session_id": {"$exists": False}},
                            {"metadata.session_id": None}
                        ]
                    }
                },
                {"$limit": 3}
            ]
            results = list(db[config.CHUNKS_COLLECTION].aggregate(pipeline))

        # 3. Format results
        for res in results:
            text = res.get("text", "")[:800]
            retrieved_texts.append(text)
            chunk_id = res.get("metadata", {}).get("chunk_id", res.get("_id"))
            retrieved_chunk_ids.add(chunk_id)
            metadata = res.get("metadata", {})
            c_id = metadata.get("contract_id", "Unknown Contract")
            if c_id:
                retrieved_contract_ids.add(c_id)
            if c_id not in chunks_by_contract:
                chunks_by_contract[c_id] = []
            chunks_by_contract[c_id].append(text)

    except Exception as e:
        print(f"❌ MongoDB Vector Search failed: {e}")

    return retrieved_texts, retrieved_chunk_ids, retrieved_contract_ids, chunks_by_contract


# ────────────────────────────────────────────────────────────────────
#  2. Knowledge Graph Matching (MongoDB Atlas or local NetworkX)
# ────────────────────────────────────────────────────────────────────

def graph_match_mongo(db, search_query, retrieved_contract_ids, session_id=None):
    """
    Match query keywords against KG nodes and expand to related edges
    from MongoDB Atlas.

    Returns:
        list[str]: Formatted triple strings.
    """
    query_lower = search_query.lower()
    matched_nodes = set()
    extracted_triples = []

    if db is None:
        return extracted_triples

    try:
        # ── Node matching ────────────────────────────────────────
        node_filter = {
            "$or": [
                {"session_id": {"$exists": False}},
                {"session_id": None},
            ]
        }
        if session_id:
            node_filter["$or"].append({"session_id": session_id})

        all_nodes = list(db[config.KG_NODES_COLLECTION].find(node_filter))
        node_types = {}

        for doc in all_nodes:
            node = doc["_id"]
            ent_type = doc.get("entity_type", "Entity")
            node_types[node] = ent_type

            if ent_type == "Clause":
                c_type = doc.get("clause_type", "")
                if c_type and c_type.lower() in query_lower:
                    matched_nodes.add(node)
            elif ent_type == "Party":
                if isinstance(node, str) and len(node) > 4 and node.lower() in query_lower:
                    matched_nodes.add(node)
            elif ent_type == "Location":
                city = doc.get("city", "")
                state = doc.get("state", "")
                country = doc.get("country", "")
                if (
                    (city and city.lower() in query_lower)
                    or (state and state.lower() in query_lower)
                    or (country and len(country) > 2 and country.lower() in query_lower)
                ):
                    matched_nodes.add(node)
            elif isinstance(node, str) and len(node) > 4 and node.lower() in query_lower:
                matched_nodes.add(node)

        # ── Edge expansion ───────────────────────────────────────
        query_filter = {
            "$and": [
                {
                    "$or": [
                        {"session_id": {"$exists": False}},
                        {"session_id": None},
                    ]
                },
                {
                    "$or": [
                        {"source_chunks": {"$in": list(retrieved_contract_ids)}},
                        {"source": {"$in": list(matched_nodes)}},
                        {"target": {"$in": list(matched_nodes)}},
                    ]
                },
            ]
        }
        if session_id:
            query_filter["$and"][0]["$or"].append({"session_id": session_id})

        edges = list(db[config.KG_EDGES_COLLECTION].find(query_filter).limit(20))

        for edge in edges:
            u, v = edge["source"], edge["target"]
            label = edge["label"]
            u_short = u[:50] if isinstance(u, str) and len(u) > 50 else u
            v_short = v[:50] if isinstance(v, str) and len(v) > 50 else v
            u_type = node_types.get(u, "Entity")
            v_type = node_types.get(v, "Entity")
            triple = f"{u_short} ({u_type}) --{label}--> {v_short} ({v_type})"
            if triple not in extracted_triples:
                extracted_triples.append(triple)

    except Exception as e:
        print(f"⚠️ Error querying MongoDB Atlas for Knowledge Graph: {e}. Falling back to empty KG.")

    return extracted_triples


def graph_match_local(G, search_query, retrieved_contract_ids):
    """
    Match query keywords against a local NetworkX DiGraph.

    Returns:
        list[str]: Formatted triple strings.
    """
    query_lower = search_query.lower()
    matched_nodes = set()
    expanded_contract_ids = set()
    extracted_triples = []

    for node, data in G.nodes(data=True):
        ent_type = data.get("entity_type", "Entity")
        if ent_type == "Clause":
            c_type = data.get("clause_type", "")
            if c_type and c_type.lower() in query_lower:
                matched_nodes.add(node)
        elif ent_type == "Party":
            if isinstance(node, str) and len(node) > 4 and node.lower() in query_lower:
                matched_nodes.add(node)
        elif ent_type == "Location":
            city = data.get("city", "")
            state = data.get("state", "")
            country = data.get("country", "")
            if (
                (city and city.lower() in query_lower)
                or (state and state.lower() in query_lower)
                or (country and len(country) > 1 and country.lower() in query_lower)
            ):
                matched_nodes.add(node)
        elif isinstance(node, str) and len(node) > 4 and node.lower() in query_lower:
            matched_nodes.add(node)

    for u, v, data in G.edges(data=True):
        if len(extracted_triples) >= 20:
            break
        source_chunks = data.get("source_chunks", [])
        if "source_chunk" in data and data["source_chunk"] not in source_chunks:
            source_chunks.append(data["source_chunk"])

        is_in_retrieved = any(chunk in retrieved_contract_ids for chunk in source_chunks)

        if is_in_retrieved or u in matched_nodes or v in matched_nodes:
            u_type = G.nodes[u].get("entity_type", "Entity")
            v_type = G.nodes[v].get("entity_type", "Entity")
            u_short = u[:50] if isinstance(u, str) and len(u) > 50 else u
            v_short = v[:50] if isinstance(v, str) and len(v) > 50 else v
            triple = f"{u_short} ({u_type}) --{data['label']}--> {v_short} ({v_type})"
            if triple not in extracted_triples:
                extracted_triples.append(triple)

            for chunk in source_chunks:
                expanded_contract_ids.add(chunk)

    return extracted_triples


# ────────────────────────────────────────────────────────────────────
#  3. Context Synthesis
# ────────────────────────────────────────────────────────────────────

def synthesize_context(extracted_triples, chunks_by_contract):
    """
    Build the final context block string from KG triples and VDB chunks.

    Returns:
        str: The assembled context (or empty string if both are empty).
    """
    context_blocks = []

    if extracted_triples:
        context_blocks.append("=== KG TRIPLES ===\n" + "\n".join(extracted_triples))

    if chunks_by_contract:
        text_blocks = []
        for contract, chunks in chunks_by_contract.items():
            header = f"### Contract: {contract}"
            body = "\n\n".join(
                f"Excerpt {i}:\n{chunk}" for i, chunk in enumerate(chunks, 1)
            )
            text_blocks.append(header + "\n" + body)
        context_blocks.append(
            "=== CONTRACT TEXT ===\n\n"
            + "\n\n---------------------------------\n\n".join(text_blocks)
        )

    return "\n\n".join(context_blocks)
