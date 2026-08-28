"""
Legal-article retriever — Phase 3
LLM-Driven Privacy Compliance Framework
Author: Aaron Joseph Jean — 25233118

Retrieves the relevant compliance-law chunks from the ChromaDB
`compliance_docs` collection for a given dimension. Uses the same
legal-BERT embedder and Chroma client as ingestion (vectordb/*).

Retrieval = semantic query + metadata filter on requirement_type
(and optionally regulation). If the filtered search returns nothing
(e.g., the requirement_type tag was never assigned during ingestion),
falls back to an unfiltered semantic search so the scorer always has
a Rule to apply.
"""

from __future__ import annotations

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llama_index.core import VectorStoreIndex
from llama_index.core.vector_stores import (
    ExactMatchFilter,
    FilterCondition,
    MetadataFilters,
)

from vectordb.db_client import get_vector_store
from vectordb.embedder import get_embedder

_index = None  # lazy singleton — loading legal-BERT is slow


def _get_index() -> VectorStoreIndex:
    global _index
    if _index is None:
        _index = VectorStoreIndex.from_vector_store(
            vector_store=get_vector_store(),
            embed_model=get_embedder(),
        )
    return _index


def retrieve_law(query: str,
                 requirement_type: str | None = None,
                 regulations: list[str] | None = None,
                 top_k: int = 4) -> list[dict]:
    """
    Returns a list of {text, regulation, article, clause, requirement_type,
    score} dicts, best match first.
    """
    index = _get_index()

    filters = None
    flist = []
    if requirement_type:
        flist.append(ExactMatchFilter(key="requirement_type", value=requirement_type))
    if regulations and len(regulations) == 1:
        # single-regulation exact filter; multi-regulation is post-filtered
        flist.append(ExactMatchFilter(key="regulation", value=regulations[0]))
    if flist:
        filters = MetadataFilters(filters=flist, condition=FilterCondition.AND)

    retriever = index.as_retriever(similarity_top_k=top_k, filters=filters)
    nodes = retriever.retrieve(query)

    # Fallback: filtered search found nothing -> retry unfiltered
    if not nodes and filters is not None:
        retriever = index.as_retriever(similarity_top_k=top_k)
        nodes = retriever.retrieve(query)

    results = []
    for n in nodes:
        md = n.metadata or {}
        if regulations and len(regulations) > 1 and md.get("regulation") not in regulations:
            continue
        results.append({
            "text": n.text,
            "regulation": md.get("regulation", "Unknown"),
            "article": md.get("article", "?"),
            "clause": md.get("clause", md.get("article", "?")),
            "requirement_type": md.get("requirement_type"),
            "score": round(float(n.score), 4) if n.score is not None else None,
        })
    return results


def retrieve_by_article(regulation: str, article: str) -> list[dict]:
    """Deterministic fetch of a specific article's chunk(s) by metadata.
    Used to anchor each dimension's Rule on its known provisions
    (dimension-anchored retrieval) so semantic near-misses (e.g. GDPR
    Art 19 'recipients' vs Art 13(1)(e) 'recipients') cannot displace
    the correct article."""
    index = _get_index()
    filters = MetadataFilters(
        filters=[ExactMatchFilter(key="regulation", value=regulation),
                 ExactMatchFilter(key="article", value=article)],
        condition=FilterCondition.AND)
    retriever = index.as_retriever(similarity_top_k=2, filters=filters)
    nodes = retriever.retrieve("legal provision")   # query irrelevant under exact filters
    return [{
        "text": n.text,
        "regulation": (n.metadata or {}).get("regulation", regulation),
        "article": (n.metadata or {}).get("article", article),
        "clause": (n.metadata or {}).get("clause", article),
        "requirement_type": (n.metadata or {}).get("requirement_type"),
        "score": None,
    } for n in nodes]


_LAW_REF_RE = None


def parse_law_refs(law_refs: str) -> list[tuple[str, str]]:
    """'GDPR Art 13(1)(e); PECR Reg 6' -> [('GDPR','13'), ('PECR','6')]."""
    import re
    global _LAW_REF_RE
    if _LAW_REF_RE is None:
        # EPRIVACY-IE must precede ePrivacy in the alternation, otherwise the
        # shorter token matches first and the national instrument is lost.
        _LAW_REF_RE = re.compile(
            r'(EPRIVACY-IE|GDPR|PECR|DPDP|CCPA|ePrivacy)\s+'
            r'(?:Art|Article|Reg|Regulation|§)\.?\s*(\d+[A-Za-z]?)',
            re.IGNORECASE)
    return [(m.group(1).upper(), m.group(2)) for m in _LAW_REF_RE.finditer(law_refs or "")]


def retrieve_for_dimension(query: str,
                           law_refs: str,
                           requirement_type: str | None = None,
                           regulations: list[str] | None = None,
                           top_k: int = 4) -> list[dict]:
    """Semantic retrieval + deterministic article anchors, deduplicated.
    Anchored articles come first so the LLM sees the canonical Rule."""
    anchored = []
    for reg, art in parse_law_refs(law_refs):
        if regulations and reg not in [r.upper() for r in regulations]:
            continue
        anchored.extend(retrieve_by_article(reg, art))

    semantic = retrieve_law(query, requirement_type=requirement_type,
                            regulations=regulations, top_k=top_k)

    seen, merged = set(), []
    for c in anchored + semantic:
        key = (c["regulation"], c["article"], c["text"][:80])
        if key not in seen:
            seen.add(key)
            merged.append(c)
    return merged[:max(top_k, len(anchored))]


def render_law_context(chunks: list[dict]) -> str:
    """Format retrieved law chunks as the IRAC 'Rule' block."""
    if not chunks:
        return ("No legal articles retrieved from the compliance database. "
                "State this in your answer and use verdict NOT_ADDRESSED "
                "with low confidence.")
    lines = []
    for c in chunks:
        lines.append(f"[{c['regulation']} — Article/Section {c['article']}]")
        lines.append(c["text"].strip())
        lines.append("")
    return "\n".join(lines).strip()


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "consent required before cookies are stored"
    for r in retrieve_law(q, top_k=3):
        print(f"{r['regulation']} Art {r['article']} (score {r['score']}): {r['text'][:120]}...")
