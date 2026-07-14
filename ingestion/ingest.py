import argparse
import os
import sys

# Ensure comp_square is in the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# NOTE: the embedder/vector-store imports are done lazily inside
# process_and_ingest() AFTER chunking. Importing sentence_transformers pulls
# in the full transformers library (slow), and the first-ever run downloads
# the legal-BERT model (~440 MB) — doing this after chunking means you see
# progress output immediately instead of an apparent hang.
from ingestion.compliance_loader import LegalDocumentChunker

def process_and_ingest(file_path: str, regulation: str, jurisdiction: str, severity: str = "high"):
    """
    Reads a text file, chunks it, embeds it, and ingests it into ChromaDB.
    """
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return
        
    text = ""
    if file_path.lower().endswith(".pdf"):
        import pdfplumber
        import re
        print(f"Extracting text from PDF {file_path}...")
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

        print("Normalizing extracted PDF text...")
        # Clean up mid-sentence line breaks caused by PDF layout
        text = re.sub(r'([a-z,;])\n+([a-z])', r'\1 \2', text)

        # Ensure 'Article X' or 'Section X' are preceded by new lines to match chunker's regex
        text = re.sub(r'(?<!\n)\s*(Article|Section)\s+(\d+)', r'\n\n\1 \2', text, flags=re.IGNORECASE)
    elif file_path.lower().endswith((".html", ".xhtml", ".htm")):
        import re
        from bs4 import BeautifulSoup
        print(f"Extracting text from HTML {file_path}...")
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
        # Drop non-content elements (nav/scripts/menus of EUR-Lex & legislation.gov.uk pages)
        for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "form"]):
            tag.decompose()
        text = soup.get_text("\n")

        print("Normalizing extracted HTML text...")
        # Collapse whitespace runs but keep paragraph structure
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        # Join headings split across lines, e.g. "Article\n7" -> "Article 7"
        text = re.sub(r'(?m)^(Article|Section|Chapter|Regulation)\s*\n\s*(\d+[A-Za-z]?)\s*$',
                      r'\1 \2', text, flags=re.IGNORECASE)
        # Ensure headings start on their own line
        text = re.sub(r'(?<!\n)\s*\b(Article|Regulation)\s+(\d+[A-Za-z]?)\s*\n',
                      r'\n\n\1 \2\n', text)
    else:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
        
    print("Chunking document by articles/sections...")
    chunker = LegalDocumentChunker(regulation, jurisdiction, severity)
    nodes = chunker.chunk_document(text, os.path.basename(file_path))
    print(f"Created {len(nodes)} chunks.")
    
    # Initialize the embedding model (lazy import — see note at top of file)
    print("Loading embedding model (nlpaueb/legal-bert-base-uncased)...")
    print("(first ever run downloads ~440 MB from HuggingFace — this can take several minutes)")
    from vectordb.db_client import get_vector_store
    from vectordb.embedder import get_embedder
    embed_model = get_embedder()
    
    # Update the node embeddings.
    # Embed the clause TEXT ONLY (metadata_mode="none"): queries at retrieval
    # time are plain text, so embedding "regulation: GDPR\narticle: 7\n..."
    # metadata alongside the clause would put nodes and queries in mismatched
    # distributions. Metadata stays available for filtering and citations.
    for node in nodes:
        node.embedding = embed_model.get_text_embedding(node.get_content(metadata_mode="none"))

    print("Connecting to ChromaDB and ingesting...")
    vector_store = get_vector_store()
    
    # Add nodes directly to the vector store index
    vector_store.add(nodes)
    
    # Alternatively build a LlamaIndex VectorStoreIndex (good for higher level retrievers)
    # index = VectorStoreIndex(nodes, vector_store=vector_store, embed_model=embed_model)
    
    print(f"Successfully ingested {len(nodes)} chunks into collection 'compliance_docs'.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest a compliance document into the vector database.")
    parser.add_argument("file", help="Path to the document text file")
    parser.add_argument("--regulation", required=True, help="Name of the regulation (e.g., GDPR)")
    parser.add_argument("--jurisdiction", required=True, help="Jurisdiction (e.g., EU, USA)")
    parser.add_argument("--severity", default="high", help="Base severity level for this regulation")
    
    args = parser.parse_args()
    process_and_ingest(args.file, args.regulation, args.jurisdiction, args.severity)
