"""
Legal GraphRAG Pipeline — Orchestrator
========================================
Thin orchestrator that delegates to specialised modules:

  * ``db``        — MongoDB connectivity
  * ``llm``       — Gemini / Groq LLM clients
  * ``retrieval`` — vector search + KG matching + context synthesis
  * ``ingestion`` — PDF parse → chunk → embed → insert → KG extraction

This file is intentionally kept lean (~170 lines).
"""

import json

import networkx as nx
import torch
from sentence_transformers import SentenceTransformer

from src.core.common import config
from src.core.common.utils import force_ipv4, sanitize_session_id
from src.core.common import db as db_module
from src.core.rag.llm import LLMManager
from src.core.rag import retrieval
from src.core.ingestion import ingestion as ingestion_module

# Ensure IPv4-only resolution before any network I/O
force_ipv4()


class LegalGraphRAG:
    """Hybrid Graph + Vector RAG engine for legal contract analysis."""

    def __init__(self):
        print("🚀 Booting Legal GraphRAG Engine...")

        # ── Embedding Model ──────────────────────────────────────
        self.device = (
            "cuda" if torch.cuda.is_available()
            else "mps" if torch.backends.mps.is_available()
            else "cpu"
        )
        self.embedder = SentenceTransformer(config.EMBEDDING_MODEL, device=self.device)

        # ── MongoDB Atlas ────────────────────────────────────────
        self.mongo_client = None
        self.db = None
        self.G = nx.DiGraph()

        if config.MONGO_URI:
            try:
                print("🔌 Connecting to MongoDB Atlas for Knowledge Graph...")
                self.mongo_client = db_module.get_mongo_client()
                self.db = db_module.get_database(self.mongo_client)
                if db_module.ping(self.db):
                    print("💾 Successfully connected to MongoDB Atlas!")
                else:
                    print("⚠️ MongoDB Atlas connection ping failed. Falling back to local JSON...")
                    self.db = None
            except Exception as e:
                print(f"⚠️ MongoDB Atlas connection failed: {e}. Falling back to local JSON...")
                self.db = None

        if self.db is None:
            import os
            if os.path.exists(config.GRAPH_PATH):
                with open(config.GRAPH_PATH, "r", encoding="utf-8") as f:
                    self.G = nx.node_link_graph(json.load(f))
                print("📊 Local Knowledge Graph (legal_kg.json) loaded successfully.")
            else:
                print("⚠️ Warning: Local Knowledge Graph file (legal_kg.json) not found. Initializing empty graph.")

        # ── LLM Clients ──────────────────────────────────────────
        self.llm = LLMManager()
        # Keep backward-compat attributes used by tests
        self.gemini_enabled = self.llm.gemini_enabled

        print(f"✅ Engine Ready ({self.llm.status_summary()})!\n")

    # ────────────────────────────────────────────────────────────
    #  Query Pipeline
    # ────────────────────────────────────────────────────────────

    def answer_query(self, query, chat_history=None, session_id=None, llm_provider=None):
        """
        Answer a user query using hybrid Graph + Vector retrieval.

        Args:
            query: Natural language question.
            chat_history: Optional list of ``{"role": ..., "content": ...}`` dicts.
            session_id: Optional session ID to scope uploaded chunks.
            llm_provider: ``'gemini'`` or ``'groq'`` (defaults to config.LLM_PROVIDER).

        Returns:
            tuple: (answer_text, retrieved_texts, extracted_triples)
        """
        provider = (llm_provider or config.LLM_PROVIDER).strip().lower()

        # Validate provider availability early
        if provider == "gemini" and not self.llm.gemini_enabled:
            raise RuntimeError(
                "Google Gemini API is selected but GEMINI_API_KEY is not configured. "
                "Please set GEMINI_API_KEY or switch LLM_PROVIDER to 'groq'."
            )
        if provider == "groq" and not self.llm.groq_enabled:
            raise RuntimeError(
                "Groq API is selected but GROQ_API_KEY is not configured. "
                "Please set GROQ_API_KEY or switch LLM_PROVIDER to 'gemini'."
            )

        if session_id:
            session_id = sanitize_session_id(session_id)

        # ── 0. Query Condensation ────────────────────────────────
        search_query = query
        if chat_history:
            search_query = self._condense_query(query, chat_history, provider)

        # ── 1. Semantic Vector Search ────────────────────────────
        query_embedding = self.embedder.encode(
            [search_query], normalize_embeddings=True
        )[0].tolist()

        texts, chunk_ids, contract_ids, chunks_by_contract = retrieval.vector_search(
            self.db, query_embedding, session_id
        )

        if not texts:
            return "No relevant context found.", [], []

        # ── 2. Knowledge Graph Matching ──────────────────────────
        if self.db is not None:
            triples = retrieval.graph_match_mongo(
                self.db, search_query, contract_ids, session_id
            )
        else:
            triples = retrieval.graph_match_local(
                self.G, search_query, contract_ids
            )

        # ── 3. Context Synthesis ─────────────────────────────────
        final_context = retrieval.synthesize_context(triples, chunks_by_contract)

        # ── 4. LLM Generation ───────────────────────────────────
        system_prompt = (
            "You are a legal AI assistant. Answer using ONLY the provided context.\n"
            "You receive KG TRIPLES (entity relationships) and CONTRACT TEXT (legal excerpts).\n"
            "If the answer is not in the context, say so. Do not hallucinate."
        )

        messages = [{"role": "system", "content": system_prompt}]
        if chat_history:
            history_subset = chat_history[-10:]
            # Ensure history doesn't start with an assistant/bot message (causes LLaMA 3 API 400 errors)
            while history_subset and history_subset[0].get("role") in ["assistant", "bot"]:
                history_subset.pop(0)
            for turn in history_subset:
                role = "assistant" if turn["role"] == "bot" else turn["role"]
                messages.append({"role": role, "content": turn["content"]})
        messages.append({"role": "user", "content": f"CONTEXT:\n{final_context}\n\nQUERY: {query}"})

        answer_text = self.llm.chat(messages, provider=provider, temperature=0.2)
        return answer_text, texts, triples

    # ────────────────────────────────────────────────────────────
    #  PDF Ingestion (delegates to ingestion module)
    # ────────────────────────────────────────────────────────────

    def ingest_pdf(self, filename, pdf_bytes, session_id):
        """Parse, chunk, embed, and upload a PDF contract."""
        return ingestion_module.ingest_pdf(
            self.db, self.embedder, self.llm, filename, pdf_bytes, session_id
        )

    # ────────────────────────────────────────────────────────────
    #  Internal Helpers
    # ────────────────────────────────────────────────────────────

    def _condense_query(self, query, chat_history, provider):
        """Rewrite a follow-up query into a standalone search query."""
        try:
            history_str = ""
            for turn in chat_history[-5:]:
                history_str += f"{turn['role'].upper()}: {turn['content']}\n"

            condensation_prompt = (
                "Given the following conversation history and a follow-up question, "
                "rephrase the follow-up question to be a standalone, self-contained search query. "
                "The standalone query must include all relevant context from the history "
                "(such as contract names, dates, or terms) so that it can be searched in "
                "a database without needing the conversation history.\n\n"
                f"Conversation History:\n{history_str}\n"
                f"Follow-up Question: {query}\n\n"
                "Provide ONLY the rephrased standalone query. "
                "Do not add any introduction, explanations, or quotes."
            )

            condensed = self.llm.generate(condensation_prompt, provider=provider, temperature=0.0)

            if condensed:
                # Strip surrounding quotes if the LLM added them
                if (condensed.startswith('"') and condensed.endswith('"')) or \
                   (condensed.startswith("'") and condensed.endswith("'")):
                    condensed = condensed[1:-1]
                print(f"🔄 Condensed Query: '{query}' ➔ '{condensed}'")
                return condensed
        except Exception as e:
            print(f"⚠️ Query condensation failed: {e}. Using raw query.")

        return query


if __name__ == "__main__":
    print("⚠️ Running standalone. Ensure the infrastructure is already built.")
    engine = LegalGraphRAG()
    print("\nTest Answer:\n", engine.answer_query("What is the governing law?")[0])