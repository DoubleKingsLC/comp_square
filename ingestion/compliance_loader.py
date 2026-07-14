import re
from typing import List, Dict, Any
from llama_index.core.schema import TextNode

class LegalDocumentChunker:
    """
    Chunks legal compliance documents into specific legal units (Articles/Clauses)
    instead of arbitrary token counts.
    """
    
    def __init__(self, regulation_name: str, jurisdiction: str, severity: str = "high"):
        self.regulation_name = regulation_name
        self.jurisdiction = jurisdiction
        self.severity = severity
        
        # Legal-unit heading regex. Alternatives (first non-empty group wins):
        #   1. "Article 7" / "Section 9" / "CHAPTER II" / "Regulation 6"   (GDPR, DPDP)
        #   2. "6.—(1)" / "6.-(1)" / "6. (1)"  UK SI regulation numbering  (PECR)
        #   3. "1798.100."  California Civil Code numbering                (CCPA/CPRA)
        self.article_pattern = re.compile(
            r'^(?:Article|Section|Chapter|Regulation)\s+(\d+[a-zA-Z]?)(?:\s*[-:.]|\s*$)'
            r'|^(\d+[A-Z]?)\.\s*(?:[—–-]\s*)?\(1\)'
            r'|^(1798\.\d+)\.',
            re.IGNORECASE | re.MULTILINE)
        
    def chunk_document(self, text: str, source_file: str) -> List[TextNode]:
        """
        Splits text by Article/Section and returns LlamaIndex TextNodes
        with appropriate metadata.
        """
        nodes = []
        
        # Find all article headers
        matches = list(self.article_pattern.finditer(text))
        
        if not matches:
            # If no matches found, fallback to chunking by double newlines or whole doc
            # This is a basic fallback for unstructured text
            parts = [p.strip() for p in text.split('\n\n') if p.strip()]
            for i, part in enumerate(parts):
                node = self._create_node(part, str(i+1), source_file)
                nodes.append(node)
            return nodes

        # Extract chunks between articles
        for i, match in enumerate(matches):
            article_num = next((g for g in match.groups() if g), match.group(0).strip())
            start_pos = match.start()
            
            # End position is the start of the next article, or end of text
            end_pos = matches[i+1].start() if i + 1 < len(matches) else len(text)
            
            chunk_text = text[start_pos:end_pos].strip()

            # Skip heading-only fragments (e.g. GDPR's internal "Section 1 —
            # Transparency" chapter headings, or table-of-contents lines):
            # they carry no legal content and pollute retrieval with wrong
            # article numbers. 120 chars is safely below any real clause.
            if chunk_text and len(chunk_text) >= 120:
                node = self._create_node(chunk_text, article_num, source_file)
                nodes.append(node)

        return nodes
        
    def _create_node(self, text: str, article_num: str, source_file: str) -> TextNode:
        """Helper to create a TextNode with standard metadata."""
        
        # Basic heuristic for requirement type. A robust implementation would use LLM
        # or more sophisticated keyword matching.
        req_type = self._determine_requirement_type(text)
        
        metadata = {
            "regulation": self.regulation_name,
            "jurisdiction": self.jurisdiction,
            "article": article_num,
            "requirement_type": req_type,
            "severity": self.severity,
            "source_file": source_file,
        }
        
        return TextNode(
            text=text,
            metadata=metadata
        )
        
    def _determine_requirement_type(self, text: str) -> str:
        """
        Simple heuristic to categorize the legal text chunk based on keywords.
        """
        text_lower = text.lower()
        
        if any(word in text_lower for word in ["cookie", "tracker", "fingerprint", "localstorage"]):
            return "cookies"
        # children before consent: children's articles almost always also mention consent
        elif any(word in text_lower for word in ["child", "children", "minor", "under 16", "under 13"]):
            return "children"
        elif any(word in text_lower for word in ["consent", "opt-in", "agree", "withdraw"]):
            return "consent"
        elif any(word in text_lower for word in ["transfer", "third country", "international", "standard contractual clauses"]):
            return "transfer"
        elif any(word in text_lower for word in ["privacy notice", "inform", "disclose", "transparency"]):
            return "disclosure"
        elif any(word in text_lower for word in ["retain", "retention", "storage limitation", "keep"]):
            return "retention"
        elif any(word in text_lower for word in ["access", "erasure", "rectification", "portability"]):
            return "rights"
        elif any(word in text_lower for word in ["security", "encryption", "pseudonymisation", "technical and organisational"]):
            return "security"
            
        return "general"
