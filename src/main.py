from src.core.ingestion.kg_builder import build_infrastructure
from src.core.rag_pipeline import LegalGraphRAG

def main():
    print("==================================================")
    print(" 🏛️  LEGAL AI GRAPH-RAG ORCHESTRATOR  🏛️")
    print("==================================================")
    
    # 1. Build Infrastructure (Vector DB + Knowledge Graph)
    print("\n[STEP 1/2] Building Infrastructure (VectorDB + KG)...")
    for step in build_infrastructure():
        pass
    
    # 2. Start QA Engine
    print("\n[STEP 2/2] Starting GraphRAG Engine...")
    engine = LegalGraphRAG()
    
    print("\n✅ System Ready! Ask your questions below (type 'exit' or 'quit' to stop).")
    
    # Conversation memory for the CLI session
    chat_history = []
    
    while True:
        try:
            query = input("\n🤔 Enter your question: ").strip()
            if query.lower() in ['exit', 'quit']:
                print("Goodbye!")
                break
            if not query:
                continue
                
            print("\n⚙️ Processing query...")
            answer, contexts, triplets = engine.answer_query(query, chat_history=chat_history)
            
            # Persist this exchange into local session memory
            chat_history.append({"role": "user", "content": query})
            chat_history.append({"role": "assistant", "content": answer})
            
            print("\n" + "="*60)
            print("🧩 [EXTRACTED KNOWLEDGE GRAPH TRIPLETS]")
            if triplets:
                for t in triplets:
                    print(f"  - {t}")
            else:
                print("  (No relevant triplets found)")
            
            print("\n📄 [PULLED CONTEXT EXCERPTS]")
            if contexts:
                for i, c in enumerate(contexts, 1):
                    print(f"\n--- Excerpt {i} ---\n{c.strip()}")
            else:
                print("  (No relevant context found)")
                
            print("\n🤖 [AI ASSISTANT ANSWER]")
            print(answer)
            print("="*60 + "\n")
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    main()
