import os

from llama_index.embeddings.huggingface import HuggingFaceEmbedding

# Default embedding model for the compliance_docs collection.
#
# NOTE (2026-07-12): we originally used `nlpaueb/legal-bert-base-uncased`
# for its legal vocabulary, but it is a raw BERT checkpoint, NOT a
# sentence-embedding model. Mean-pooled vanilla BERT produces near-uniform
# cosine similarities (~0.7 for everything), making retrieval effectively
# random — verified empirically: a cookie-consent query ranked DPDP
# penalty clauses above GDPR Art 7 / PECR Reg 6. Sentence-trained encoders
# are required for retrieval; legal-BERT remains an option for future
# fine-tuning experiments.
#
# Override with:  export EMBED_MODEL=<huggingface model name>
DEFAULT_EMBED_MODEL = "sentence-transformers/all-mpnet-base-v2"


def get_embedder() -> HuggingFaceEmbedding:
    """
    Returns the HuggingFace embedding model used for BOTH ingestion and
    query embedding (they must always match).
    """
    model_name = os.environ.get("EMBED_MODEL", DEFAULT_EMBED_MODEL)
    return HuggingFaceEmbedding(model_name=model_name)
