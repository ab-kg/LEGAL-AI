import os
import sys
import json
import uuid
import certifi
import torch

from pymongo import MongoClient
from sentence_transformers import SentenceTransformer

# Add project root to Python path so 'src' module can be found
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from src.core.ingestion.data_loader import load_cuad_dataset
from src.core.common.utils import chunk_text


# =====================================================================
# ⚙️ CONFIGURATION
# =====================================================================

from dotenv import load_dotenv
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")

DB_NAME = "legal_rag"
COLLECTION_NAME = "chunks"

# Better settings for legal contracts
CHUNK_SIZE = 500
OVERLAP = 100

# Number of unique CUAD contracts to index
NUM_CONTRACTS = 1000

# Embedding model
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

# Batch size for embeddings
BATCH_SIZE = 32


# =====================================================================
# 🛠️ HELPER FUNCTIONS
# =====================================================================

# chunk_text is now imported from src.core.common.utils


# =====================================================================
# 🚀 MAIN PIPELINE
# =====================================================================

def main():

    # -------------------------------------------------------------
    # Validate Mongo URI
    # -------------------------------------------------------------

    if not MONGO_URI:
        raise ValueError(
            "❌ MONGO_URI environment variable missing."
        )

    # -------------------------------------------------------------
    # Device Selection
    # -------------------------------------------------------------

    print("⚡ Selecting device...")

    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"

    print(f"✅ Using device: [{device.upper()}]")

    # -------------------------------------------------------------
    # Load Embedding Model
    # -------------------------------------------------------------

    print("\n🧠 Loading embedding model...")

    embedder = SentenceTransformer(
        EMBEDDING_MODEL,
        device=device
    )

    # -------------------------------------------------------------
    # MongoDB Connection
    # -------------------------------------------------------------

    print("\n📥 Connecting to MongoDB Atlas...")

    client = MongoClient(
        MONGO_URI,
        tlsCAFile=certifi.where()
    )

    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]

    # -------------------------------------------------------------
    # Clear Existing Collection
    # -------------------------------------------------------------

    print("🧹 Clearing old indexed chunks...")

    collection.delete_many({})

    # -------------------------------------------------------------
    # Load contract_data.json to align VDB chunk contract_ids with KG file_ids
    contract_data_path = os.path.join("resources", "research", "import-graph", "contract_data.json")
    if not os.path.exists(contract_data_path):
        contract_data_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "resources", "research", "import-graph", "contract_data.json")
        )
    
    valid_file_ids = set()
    if os.path.exists(contract_data_path):
        try:
            with open(contract_data_path, "r", encoding="utf-8") as f:
                contracts_meta = json.load(f)
            valid_file_ids = {c.get("file_id") for c in contracts_meta if c.get("file_id")}
            print(f"📖 Loaded {len(valid_file_ids)} valid contract IDs from contract_data.json")
        except Exception as e:
            print(f"⚠️ Error loading contract_data.json: {e}")
    else:
        print("⚠️ Warning: contract_data.json not found. Not filtering by KG files.")

    # Load Dataset
    # -------------------------------------------------------------

    print("\n📥 Loading CUAD dataset...")

    dataset = load_cuad_dataset()

    # -------------------------------------------------------------
    # Group and filter by Title/Filename (IMPORTANT for KG Alignment)
    # -------------------------------------------------------------

    contracts_by_title = {}
    for item in dataset:
        title = item.get("title", "")
        context = item.get("context", "")
        if title and context:
            title = title.strip()
            # Filter to only index contracts that exist in the Knowledge Graph
            if valid_file_ids and title not in valid_file_ids:
                continue
            contracts_by_title[title] = context

    print(
        f"📊 Aligned contracts found: "
        f"{len(contracts_by_title)}"
    )

    # -------------------------------------------------------------
    # Select Subset
    # -------------------------------------------------------------

    titles_to_index = list(contracts_by_title.keys())[:NUM_CONTRACTS]

    print(
        f"🚀 Indexing {len(titles_to_index)} contracts..."
    )

    total_chunks_indexed = 0

    # -------------------------------------------------------------
    # Process Contracts
    # -------------------------------------------------------------

    for doc_idx, title in enumerate(titles_to_index):
        contract_text = contracts_by_title[title]

        print(
            f"\n📄 Processing Contract "
            f"{doc_idx + 1}/{len(titles_to_index)}: {title}"
        )

        contract_id = title

        # ---------------------------------------------------------
        # Chunk Contract
        # ---------------------------------------------------------

        chunks = chunk_text(
            contract_text,
            chunk_size=CHUNK_SIZE,
            overlap=OVERLAP
        )

        print(
            f"   -> Generated {len(chunks)} chunks"
        )

        if not chunks:
            print("   ⚠️ Skipping empty contract")
            continue

        # ---------------------------------------------------------
        # Generate Embeddings
        # ---------------------------------------------------------

        print("   🧠 Generating embeddings...")

        embeddings = embedder.encode(
            chunks,
            batch_size=BATCH_SIZE,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False
        )

        # ---------------------------------------------------------
        # Build Mongo Payload
        # ---------------------------------------------------------

        payload = []

        for chunk_idx, chunk_text_value in enumerate(chunks):

            payload.append({
                "_id": str(uuid.uuid4()),

                "text": chunk_text_value,

                "embedding": embeddings[chunk_idx].tolist(),

                "metadata": {
                    "contract_id": contract_id,
                    "contract_index": doc_idx,
                    "chunk_index": chunk_idx,
                    "word_count": len(
                        chunk_text_value.split()
                    )
                }
            })

        # ---------------------------------------------------------
        # Insert Into MongoDB
        # ---------------------------------------------------------

        if payload:

            collection.insert_many(payload)

            total_chunks_indexed += len(payload)

            print(
                f"   ✅ Indexed {len(payload)} chunks"
            )

    # =================================================================
    # FINAL STATS
    # =================================================================

    print("\n══════════════════════════════════════")
    print("🏆 INDEXING COMPLETE")
    print("══════════════════════════════════════")

    print(f"📦 Contracts indexed : {len(titles_to_index)}")
    print(f"📄 Total chunks      : {total_chunks_indexed}")

    # =================================================================
    # VECTOR SEARCH VERIFICATION
    # =================================================================

    print("\n🔍 Running verification vector search...")

    test_query = "governing law clause"

    query_vector = embedder.encode(
        [test_query],
        normalize_embeddings=True
    )[0].tolist()

    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 100,
                "limit": 3
            }
        },
        {
            "$project": {
                "text": 1,
                "metadata": 1,
                "score": {
                    "$meta": "vectorSearchScore"
                }
            }
        }
    ]

    try:

        results = list(
            collection.aggregate(pipeline)
        )

        if not results:

            print(
                "⚠️ No vector search results returned."
            )

        else:

            print("\n🎉 Verification successful!")

            for idx, result in enumerate(results):

                print("\n----------------------------------")
                print(f"Result #{idx + 1}")
                print("----------------------------------")

                print(
                    f"Score : "
                    f"{result.get('score'):.4f}"
                )

                print(
                    f"Chunk : "
                    f"{result.get('metadata', {}).get('chunk_index')}"
                )

                preview = result.get("text", "")[:300]

                print(f"Preview:\n{preview}...")

    except Exception as e:

        print("\n❌ Vector search failed")
        print(str(e))


# =====================================================================
# ENTRYPOINT
# =====================================================================

if __name__ == "__main__":
    main()