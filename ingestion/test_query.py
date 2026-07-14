import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llama_index.core import VectorStoreIndex
from vectordb.db_client import get_vector_store
from vectordb.embedder import get_embedder

def test_retrieval(query: str, top_k: int = 4):
    print(f"\n--- Testing Retrieval ---")
    print(f"Query: '{query}'")
    
    # Load ChromaDB Collection
    vector_store = get_vector_store()
    
    # Construct index from existing store
    embed_model = get_embedder()
    print("Connecting to LlamaIndex vector store (existing DB)...")
    index = VectorStoreIndex.from_vector_store(
        vector_store=vector_store,
        embed_model=embed_model,
    )
    
    # Run query
    retriever = index.as_retriever(similarity_top_k=top_k)
    nodes = retriever.retrieve(query)
    
    print(f"\nFound {len(nodes)} relevant chunks:\n")
    for i, node in enumerate(nodes):
        print(f"Result {i+1}:")
        print(f"Article: {node.metadata.get('article', 'Unknown')}")
        print(f"Requirement Type: {node.metadata.get('requirement_type', 'Unknown')}")
        print(f"Similarity Score: {node.score:.4f}")
        print("-" * 40)
        print(node.text)
        print("=" * 60)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
    else:
        q = "What are the rules regarding withdrawal of user consent?"
    test_retrieval(q)
