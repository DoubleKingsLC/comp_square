from pydantic import BaseModel, Field
from typing import List, Optional

class PolicySection(BaseModel):
    title: str = Field(..., description="The title of the section (e.g., 'Data Collection', 'Security')")
    content: str = Field(..., description="The raw text content belonging to this section")
    summary: str = Field(..., description="A 1-sentence summary of what this section covers")

class SegmentedPolicy(BaseModel):
    sections: List[PolicySection] = Field(..., description="The privacy policy divided into logical, mutually exclusive sections")

class SectionEvaluation(BaseModel):
    section_name: str = Field(..., description="The name of the section evaluated")
    status: str = Field(..., description="Must be one of: 'Compliant', 'Non-Compliant', or 'Missing Information'")
    evaluation_notes: str = Field(..., description="Explanation of why it is compliant or non-compliant.")
    breached_articles: List[str] = Field(..., description="List of exact legal citations from the ground-truth text that were breached or missing (e.g., 'GDPR Article 13', 'DPDP Section 5(1)'). Leave empty if Compliant.")
    security_controls_mentioned: List[str] = Field(..., description="Any technical security features promised in this specific section (e.g. 'AES encryption', 'cookies').")

class OmissionCheck(BaseModel):
    missing_mandatory_clauses: List[str] = Field(..., description="Any legally required clauses that were totally missing from the entire privacy policy.")
    overall_compliance_score: int = Field(..., description="A score from 0-100 indicating overall compliance level across all sections and omissions.")

class EvaluationResult(BaseModel):
    compliance_score: int = Field(..., description="A score from 0-100 indicating compliance level")
    section_evaluations: List[SectionEvaluation] = Field(..., description="Detailed breakdown of compliance per section")
    missing_mandatory_clauses: List[str] = Field(..., description="Required clauses that were entirely omitted")
    security_controls: List[str] = Field(..., description="Aggregated list of exact technical claims for Phase 2")
