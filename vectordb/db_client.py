import os
import chromadb
from llama_index.vector_stores.chroma import ChromaVectorStore

# By default, store the vector database in the root of the project
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chroma_db")

def get_vector_store(collection_name: str = "compliance_docs", db_path: str = DEFAULT_DB_PATH) -> ChromaVectorStore:
    """
    Initializes and returns a ChromaVectorStore for a given collection.
    
    Args:
        collection_name (str): Name of the Chroma collection. Defaults to 'compliance_docs'.
        db_path (str): Path to store the Chroma database files.
        
    Returns:
        ChromaVectorStore: The LlamaIndex wrapper for the Chroma DB collection.
    """
    # Create the directory if it doesn't exist
    os.makedirs(db_path, exist_ok=True)
    
    # Initialize the Chroma client
    chroma_client = chromadb.PersistentClient(path=db_path)
    
    # Get or create the collection
    chroma_collection = chroma_client.get_or_create_collection(collection_name)
    
    # Wrap it in the LlamaIndex ChromaVectorStore
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    
    return vector_store

def get_collection(collection_name: str = "compliance_docs", db_path: str = DEFAULT_DB_PATH):
    """
    Returns the raw Chroma collection object if direct DB operations are needed.
    """
    chroma_client = chromadb.PersistentClient(path=db_path)
    return chroma_client.get_or_create_collection(collection_name)
