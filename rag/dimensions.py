"""
Compliance dimension definitions — Phase 3
LLM-Driven Privacy Compliance Framework
Author: Aaron Joseph Jean — 25233118

The 14 scoring dimensions from RAG_Pipeline_Architecture.md §11.

Design principles from the literature:
  * Zimmeck et al. (NDSS 2017): keep a CLOSED set of practices checkable in
    both policy text and observed behaviour — every behavioural dimension
    maps to a defined evidence key produced by ingestion/har_extractor.py.
  * Xie et al. (USENIX Sec 2025) systematized 34 clauses across 10 laws;
    our 14 dimensions cover their four themes (data collection & use,
    user rights, consent, disclosure). Dimensions we deliberately omit
    (e.g., biometric-specific clauses) are out of scope for web telemetry.

Each dimension:
  id                : stable identifier (used in reports)
  name              : human-readable title
  issue             : the IRAC "Issue" — the question the LLM must answer
  law_refs          : indicative articles (retrieval hint + report citation)
  requirement_type  : metadata filter for compliance_docs retrieval
  retrieval_query   : semantic query for the vector store
  evidence_keys     : keys from har_extractor evidence dict ([] = policy-only)
  severity          : critical | high | medium | low
"""

from __future__ import annotations

SEVERITY_WEIGHTS = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}

DIMENSIONS = [
    {
        "id": "pre_consent_tracking",
        "name": "Pre-consent tracking cookies",
        "issue": "Does the site install profiling/tracking cookies before the user gives consent?",
        "law_refs": "GDPR Art 7; PECR Reg 6; EPRIVACY-IE Reg 5",
        "requirement_type": "cookies",
        "retrieval_query": "consent must be obtained before storing cookies or tracking technologies on user equipment",
        "evidence_keys": ["pre_consent_profiling_cookies", "js_set_profiling_cookies", "consent_ui_detected"],
        "severity": "critical",
    },
    {
        "id": "consent_mechanism_validity",
        "name": "Validity of the consent mechanism",
        "issue": "Is consent requested via a clear, affirmative, freely-given opt-in mechanism (not implied, pre-ticked, or absent)?",
        "law_refs": "GDPR Art 7(1), 7(2), 4(11)",
        "requirement_type": "consent",
        "retrieval_query": "conditions for valid consent freely given specific informed unambiguous affirmative action",
        "evidence_keys": ["consent_ui_detected"],
        "severity": "critical",
    },
    {
        "id": "tracking_without_consent",
        "name": "Trackers and fingerprinting without consent",
        "issue": "Are third-party trackers contacted or fingerprinting techniques executed without user consent?",
        "law_refs": "PECR Reg 6; EPRIVACY-IE Reg 5; ePrivacy Art 5(3)",
        "requirement_type": "cookies",
        "retrieval_query": "storing or accessing information on terminal equipment tracking devices fingerprinting requires consent",
        "evidence_keys": ["tracker_requests", "fingerprinting_alarms"],
        "severity": "critical",
    },
    {
        "id": "disclosure_of_data_collected",
        "name": "Disclosure of data collected",
        "issue": "Does the policy disclose the categories of personal data actually collected, matching observed behaviour?",
        "law_refs": "GDPR Art 13(1)(c)",
        "requirement_type": "disclosure",
        "retrieval_query": "information to be provided about purposes of processing and categories of personal data collected",
        "evidence_keys": ["declared_vs_actual"],
        "severity": "high",
    },
    {
        "id": "disclosure_of_third_parties",
        "name": "Disclosure of third-party recipients",
        "issue": "Are the third parties that actually receive data disclosed in the policy?",
        "law_refs": "GDPR Art 13(1)(e)",
        "requirement_type": "disclosure",
        "retrieval_query": "recipients or categories of recipients of the personal data must be disclosed",
        "evidence_keys": ["third_party_domains", "declared_vs_actual"],
        "severity": "high",
    },
    {
        "id": "cookie_retention_period",
        "name": "Cookie/data retention period",
        "issue": "Are cookie lifetimes consistent with the retention periods the policy declares, and are they proportionate?",
        "law_refs": "GDPR Art 5(1)(e), 13(2)(a)",
        "requirement_type": "retention",
        "retrieval_query": "personal data kept no longer than necessary storage period retention",
        "evidence_keys": ["pre_consent_profiling_cookies", "js_set_profiling_cookies"],
        "severity": "high",
    },
    {
        "id": "right_to_withdraw",
        "name": "Right to withdraw consent",
        "issue": "Does the policy inform users of the right to withdraw consent, and is withdrawal as easy as giving consent?",
        "law_refs": "GDPR Art 7(3)",
        "requirement_type": "consent",
        "retrieval_query": "right to withdraw consent at any time as easy as giving consent",
        "evidence_keys": [],
        "severity": "high",
    },
    {
        "id": "cross_border_transfers",
        "name": "Cross-border data transfers",
        "issue": "Does the policy address international transfers, given data flows to third-country services observed at runtime?",
        "law_refs": "GDPR Art 44 (Ch V, Art 44-49); GDPR Art 13(1)(f)",
        "requirement_type": "transfer",
        "retrieval_query": "transfer of personal data to third countries safeguards adequacy decision",
        "evidence_keys": ["third_party_domains"],
        "severity": "high",
    },
    {
        "id": "childrens_data",
        "name": "Children's data protection",
        "issue": "Does the policy address processing of children's data and age verification where applicable?",
        "law_refs": "GDPR Art 8; DPDP §9",
        "requirement_type": "children",
        "retrieval_query": "child consent parental authorisation age verification minors data",
        "evidence_keys": [],
        "severity": "high",
    },
    {
        "id": "data_subject_rights",
        "name": "Data subject rights disclosure",
        "issue": "Does the policy inform users of their rights (access, rectification, erasure, portability, objection, complaint)?",
        "law_refs": "GDPR Art 13(2)(b)-(f), Art 15-21",
        "requirement_type": "rights",
        "retrieval_query": "data subject rights access rectification erasure portability object lodge complaint",
        "evidence_keys": [],
        "severity": "medium",
    },
    {
        "id": "lawful_basis",
        "name": "Lawful basis stated",
        "issue": "Does the policy state a lawful basis for each processing purpose?",
        "law_refs": "GDPR Art 6, 13(1)(c)",
        "requirement_type": "consent",
        "retrieval_query": "lawful basis for processing consent contract legitimate interests legal obligation",
        "evidence_keys": [],
        "severity": "medium",
    },
    {
        "id": "data_minimisation",
        "name": "Data minimisation",
        "issue": "Is observed data collection limited to what the declared purposes require?",
        "law_refs": "GDPR Art 5(1)(c)",
        "requirement_type": "disclosure",
        "retrieval_query": "personal data adequate relevant limited to what is necessary minimisation",
        "evidence_keys": ["declared_vs_actual", "third_party_domains"],
        "severity": "medium",
    },
    {
        "id": "dpo_contact",
        "name": "Controller/DPO contact details",
        "issue": "Does the policy identify the controller and provide contact details (and DPO where required)?",
        "law_refs": "GDPR Art 13(1)(a)(b), Art 37",
        "requirement_type": "disclosure",
        "retrieval_query": "identity and contact details of the controller data protection officer",
        "evidence_keys": [],
        "severity": "low",
    },
    {
        "id": "policy_versioning",
        "name": "Policy effective date and versioning",
        "issue": "Does the policy carry an effective/last-updated date and describe how changes are notified?",
        "law_refs": "GDPR Art 13 (transparency good practice)",
        "requirement_type": "disclosure",
        "retrieval_query": "transparent information policy updates notification of changes",
        "evidence_keys": [],
        "severity": "low",
    },
    {
        "id": "security_headers",
        "name": "Technical security measures",
        "issue": "Do observed transport security measures (HTTPS, security headers) support the policy's security claims?",
        "law_refs": "GDPR Art 5(1)(f), Art 32",
        "requirement_type": "security",
        "retrieval_query": "appropriate technical and organisational measures security of processing integrity confidentiality",
        "evidence_keys": [],
        "severity": "medium",
    },
]

DIMENSIONS_BY_ID = {d["id"]: d for d in DIMENSIONS}


def get_dimensions(ids: list | None = None, behavioural_only: bool = False) -> list:
    dims = DIMENSIONS if not ids else [DIMENSIONS_BY_ID[i] for i in ids]
    if behavioural_only:
        dims = [d for d in dims if d["evidence_keys"]]
    return dims
