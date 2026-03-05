# RAG Compliance Pipeline — Architecture & Implementation Guide

**Project:** LLM-Driven Privacy Compliance Framework
**Author:** Aaron Joseph Jean — 25233118
**Last Updated:** 2026-03-05 (Revised: clarified runtime vs. pre-loaded inputs)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Pipeline Diagram](#2-pipeline-diagram)
3. [Layer 1 — Ingestion](#3-layer-1--ingestion)
   - 3.1 Compliance Documents
   - 3.2 Website Policy Documents
   - 3.3 HAR + Telemetry
4. [Layer 2 — Chunking & Metadata](#4-layer-2--chunking--metadata)
5. [Layer 3 — Vector Database](#5-layer-3--vector-database)
6. [Layer 4 — RAG Query Engine](#6-layer-4--rag-query-engine)
7. [Layer 5 — LLM Scorer & Report Builder](#7-layer-5--llm-scorer--report-builder)
8. [Implementation Steps](#8-implementation-steps)
9. [Tool Options](#9-tool-options)
10. [File Structure](#10-file-structure)
11. [Compliance Dimensions Reference](#11-compliance-dimensions-reference)

---

## 1. System Overview

The pipeline uses two distinct input categories:

### Pre-loaded (once, into Vector DB)

| Input | Source | Purpose |
|---|---|---|
| **Compliance Documents** | GDPR, HIPAA, DPDP, CCPA, PECR | Ground truth — what the law requires. Static. Loaded once. |

### Runtime Inputs (per website scan, passed directly to LLM)

| Input | Source | Purpose |
|---|---|---|
| **Website Policy Documents** | `policy_scraper_2.py` output (`.md`) | What the website claims to do |
| **HAR + Telemetry** | `telemetry_collector.py` output (`.har`, `.json`) | What the website actually does |

**Why this distinction matters:**
- Compliance regulations are **static** — GDPR doesn't change weekly. Pre-loading them into a vector DB lets you retrieve the exact relevant articles efficiently without passing the entire GDPR text to the LLM every time.
- Website policies and HAR files are **site-specific and short-lived**. They change per scan. The LLM needs to read them **in full** to catch nuances — chunking them into a vector DB would lose context and introduce retrieval misses. Pass them directly.

At runtime, the pipeline:
1. **Retrieves** the relevant compliance law chunks from the vector DB
2. **Injects** the scraped policy text + HAR behavioral evidence as direct context
3. **LLM scores** each compliance dimension and cites the specific article + the specific policy clause that passes/fails

The LLM produces:
- A **score per compliance dimension** (0–100)
- A **citation** to the exact law article breached
- **Behavioral evidence** from the HAR file backing the finding
- A **recommendation** tied to the specific policy section that needs fixing

---

## 2. Pipeline Diagram

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PRE-LOAD PHASE (run once)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─────────────────────────────────────────┐
│  Compliance Regulations                 │
│  GDPR, HIPAA, DPDP, CCPA, PECR (text)  │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│  compliance_loader.py                   │
│  • Parse PDF/text                       │
│  • Split by article/clause              │
│  • Tag: regulation, article, clause,    │
│    requirement_type, severity           │
│  • Embed with legal-BERT                │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│  VECTOR DATABASE                        │
│  ┌───────────────────────────────────┐  │
│  │  compliance_docs collection       │  │
│  │  GDPR Art 7.1, Art 13.1.e, ...   │  │
│  │  DPDP Art 9, CCPA §1798.100 ...  │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  RUNTIME PHASE (per website scan)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Input:  https://www.instagram.com
            │
            ├──► policy_scraper_2.py  ──►  privacy_policy.md
            │                              cookie_policy.md
            │
            └──► telemetry_collector.py ─► site.har
                                           telemetry.json

                   │
                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  COMPLIANCE SCORER  (rag/scorer.py)                                 │
│                                                                     │
│  For each compliance dimension:                                     │
│    1. Query vector DB ──► retrieve top-k compliance law chunks      │
│    2. Read policy .md files in full ──► inject as direct context    │
│    3. Parse HAR events ──► inject behavioral evidence as context    │
│    4. Assemble prompt → send to LLM                                 │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         LLM SCORER                                  │
│  Claude Haiku  ──  per-dimension scoring  ──  structured JSON       │
│  Claude Sonnet ──  final report assembly  ──  human-readable        │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      COMPLIANCE REPORT                              │
│  • Overall score (0–100) weighted by severity                       │
│  • Per-dimension score + verdict (PASS / FAIL / PARTIAL)            │
│  • Exact law citation (GDPR Article 7.1)                            │
│  • Behavioral evidence from HAR                                     │
│  • Policy section that caused the breach                            │
│  • Recommended fix                                                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Layer 1 — Ingestion

> **Key design rule:** Only compliance regulation documents are stored in the vector DB. Website policies and HAR files are runtime inputs — read in full and injected directly into the LLM prompt. This avoids retrieval misses caused by chunking site-specific content and ensures the LLM sees the complete policy text rather than fragments.

### 3.1 Compliance Documents (Pre-loaded into Vector DB)

**What to collect:**

| Regulation | Jurisdiction | Key Focus |
|---|---|---|
| GDPR (2016/679) | EU / EEA | Consent, data minimisation, user rights, transfers |
| PECR 2003 | UK | Cookie consent before tracking |
| DPDP Act 2023 | India | Consent, data fiduciary duties, children's data |
| CCPA / CPRA | California, USA | Right to opt-out, sale of data, disclosure |
| HIPAA (45 CFR 164) | USA | Health data, safeguards, breach notification |
| ISO 27001 | International | Security controls (optional) |

**Where to get them (free):**
- GDPR: `eur-lex.europa.eu` — HTML and PDF versions
- DPDP: `meity.gov.in`
- CCPA: `leginfo.legislature.ca.gov`
- PECR: `legislation.gov.uk`

**Chunking strategy — chunk by legal unit (article / section / clause), NOT by token count:**

```
GDPR Article 7 — Conditions for consent
  ├── Chunk 1: Article 7(1) — controller must demonstrate consent
  ├── Chunk 2: Article 7(2) — written consent, clear language
  ├── Chunk 3: Article 7(3) — right to withdraw
  └── Chunk 4: Article 7(4) — no conditional consent
```

**Metadata schema per chunk:**

```json
{
  "text": "Article 7(1): Where processing is based on consent, the controller shall be able to demonstrate that the data subject has consented...",
  "metadata": {
    "regulation": "GDPR",
    "jurisdiction": "EU",
    "article": "7",
    "clause": "7.1",
    "title": "Conditions for consent",
    "requirement_type": "consent",
    "obligation": "controller",
    "severity": "high",
    "source_file": "gdpr_full.txt",
    "section": "Chapter II"
  }
}
```

**`requirement_type` taxonomy** (used for targeted retrieval):

| Value | Covers |
|---|---|
| `consent` | How consent must be obtained and recorded |
| `disclosure` | What must be disclosed in the policy |
| `retention` | How long data may be kept |
| `transfer` | Cross-border data transfers |
| `rights` | Data subject rights (access, erasure, portability) |
| `security` | Technical and organisational measures |
| `children` | Special rules for minors |
| `cookies` | Cookie-specific consent requirements |

---

### 3.2 Website Policy Documents (Runtime — injected directly into LLM)

Output of `policy_scraper_2.py` — already saved as markdown with YAML front matter.

**Do NOT chunk or store in vector DB.** Pass the full `.md` file content as direct LLM context at runtime. Typical policy documents are 2,000–15,000 words — well within a 200K context window.

**Runtime context format:**

```python
policy_context = f"""
WEBSITE PRIVACY POLICY ({domain})
Source: {source_url}
Scraped: {scraped_at}
---
{privacy_policy_full_text}

WEBSITE COOKIE POLICY ({domain})
Source: {cookie_policy_url}
---
{cookie_policy_full_text}
"""
```

If a policy is extremely long (>50K words), then chunk by `## heading` sections and pass only the sections relevant to the compliance dimension being scored.

---

### 3.3 HAR + Telemetry (Runtime — parsed and summarized for LLM)

This is the **behavioral evidence layer** — the critical differentiator. It lets the system say *"the site does X, despite claiming Y"*.

**Do NOT store in vector DB.** At runtime, `har_extractor.py` parses the `.har` file and produces a structured behavioral summary that is injected into the LLM prompt.

**Extract from `.har` file:**

| Event Type | What to Extract | Compliance Signal |
|---|---|---|
| `pre_consent_cookie` | Cookies set before consent dialog interaction | GDPR Art 7, PECR Reg 6 |
| `third_party_transfer` | Requests to non-owned domains | GDPR Art 13 (disclosure) |
| `tracker` | Known tracker domains (via disconnect.me list) | GDPR Art 6 (legal basis) |
| `fingerprint` | Canvas/WebGL/font fingerprinting calls | PECR, ePrivacy |
| `declared_vs_actual` | Cookies in policy vs cookies actually set | GDPR Art 5.1 (accuracy) |
| `long_retention` | Cookies with duration > declared retention | GDPR Art 5.1.e |

**Runtime context format (injected per LLM call):**

```python
har_context = f"""
BEHAVIORAL EVIDENCE — {domain} ({scan_date})
HAR file: {har_file}

Pre-consent cookies detected (set before any consent interaction):
  - Cookie '_fbp' (facebook.com) set 340ms after page load. Duration: 90 days.
  - Cookie '_ga' (google-analytics.com) set 120ms after page load. Duration: 2 years.

Third-party domains contacted (not declared in cookie policy):
  - pixel.facebook.com
  - analytics.tiktok.com
  - [12 others]

Total third-party domains: 47
Declared in policy: 35
Undeclared: 12
"""
```

The raw HAR JSON schema (for `har_extractor.py` internal use):

```json
{
  "domain": "www.instagram.com",
  "evidence_type": "pre_consent_cookie",
  "cookie_name": "_fbp",
  "cookie_domain": "facebook.com",
  "third_party": true,
  "timing_ms": 340,
  "timing_relative_to_consent": "before",
  "cookie_duration_days": 90
}
```

---

## 4. Layer 2 — Chunking & Metadata

### Chunk Size Guidelines (Compliance Docs only)

| Collection | Chunk Size | Overlap | Reason |
|---|---|---|---|
| `compliance_docs` | 1 article / clause | 0 | Legal units must stay intact for valid citations |

Website policies and HAR events are **not chunked for vector DB** — they are passed in full as runtime context.

### Why Metadata Matters

The metadata on compliance chunks is what makes the output **explainable** and **citation-quality**. When the LLM says:

> *"Score: 12/100 — FAIL"*

The metadata enables it to instead say:

> *"Score: 12/100 — FAIL. Breach: GDPR Article 7(1) (consent must precede processing). Evidence: HAR file shows cookie `_fbp` (facebook.com, 90-day duration) set 340ms before consent dialog appeared. Policy claim: Cookie Policy section 'Why do we use cookies?' states consent is obtained before personalisation cookies are set — this is contradicted by observed behaviour."*

---

## 5. Layer 3 — Vector Database

### Single Collection

```
vector_db/
└── compliance_docs      ← legal requirements only (static, loaded once)
```

The vector DB is queried at runtime to retrieve the specific law articles relevant to the compliance dimension being scored. Website policies and HAR data are **not stored here** — they are read from disk and injected directly into the LLM prompt.

### Metadata Filtering at Runtime

```python
# "What does GDPR say about pre-consent cookie requirements?"
db.query(
    vector=embed("cookie consent required before tracking"),
    filter={"regulation": "GDPR", "requirement_type": "cookies"},
    top_k=5
)

# "What does DPDP say about children's data?"
db.query(
    vector=embed("children minors consent data"),
    filter={"regulation": "DPDP", "requirement_type": "children"},
    top_k=3
)

# Multi-jurisdiction: all regulations covering consent
db.query(
    vector=embed("consent must precede processing"),
    filter={"requirement_type": "consent"},
    top_k=8
)
```

### Tool Options — Vector Database

| Tool | Type | Cost | Best For |
|---|---|---|---|
| **Chroma** | Open source, local | Free | Development, prototyping |
| **Qdrant** | Open source, self-host or cloud | Free (self-host) / ~$25/mo (cloud) | Production — best metadata filtering |
| **Weaviate** | Open source, self-host or cloud | Free (self-host) / free tier cloud | Hybrid search built in |
| **Pinecone** | Managed cloud | Free tier (1 index) / ~$70/mo | Scale, no infra management |
| **pgvector** | Postgres extension | Free | Already using Postgres |
| **Milvus** | Open source, self-host | Free | High-volume, on-prem |

**Recommendation:**
- **Phase 1 (development):** Chroma — zero setup, works locally, Python-native
- **Phase 2 (production):** Qdrant — best payload filtering, free self-hosted, Docker one-liner

---

## 6. Layer 4 — RAG Query Engine

### Per-Dimension Query Flow

For each compliance dimension:

1. **Retrieve** relevant compliance law chunks from vector DB (semantic + metadata filter)
2. **Load** full policy markdown files from disk (privacy_policy.md, cookie_policy.md)
3. **Parse** HAR file → extract behavioral events relevant to this dimension
4. **Assemble** the three-part context window:

```
┌──────────────────────────────────────────────┐
│  COMPLIANCE REQUIREMENT (retrieved from DB)  │
│  GDPR Article 7(1): Consent must be freely   │
│  given, specific, informed and unambiguous   │
│  prior to processing...                      │
├──────────────────────────────────────────────┤
│  WEBSITE POLICY CLAIM (full text, from disk) │
│  "We only use personalisation cookies after  │
│  you have given us your explicit consent..." │
├──────────────────────────────────────────────┤
│  BEHAVIOURAL EVIDENCE (parsed from HAR)      │
│  Cookie '_fbp' (facebook.com) set 340ms      │
│  after page load, before any consent         │
│  interaction. Duration: 90 days.             │
└──────────────────────────────────────────────┘
```

### Hybrid Search (for compliance_docs retrieval)

Use **dense + sparse search** for best recall on legal text:
- **Dense (semantic):** catches paraphrasing — "users must agree before tracking" matches "prior consent required"
- **Sparse (BM25/keyword):** catches exact legal terms — "data subject", "Article 7", "lawful basis"

Weaviate has hybrid search built in. For Chroma/Qdrant, run both and merge results.

---

## 7. Layer 5 — LLM Scorer & Report Builder

### Structured Scoring Prompt

```
[SYSTEM]
You are a privacy compliance auditor. Score the website's compliance
with the given legal requirement on a scale of 0-100.
0   = clear violation with behavioural evidence
50  = partial compliance or ambiguous policy language
100 = fully compliant with clear policy language

Always return valid JSON matching the schema provided.

[USER]
COMPLIANCE REQUIREMENT:
{gdpr_article_text}

WEBSITE POLICY CLAIM:
Domain: {domain}
Section: {section_heading}
Text: {policy_chunk_text}

BEHAVIOURAL EVIDENCE (HAR):
{har_event_summaries}

Return JSON:
{
  "dimension": "<string>",
  "score": <0-100>,
  "verdict": "PASS" | "FAIL" | "PARTIAL",
  "breach": {
    "regulation": "<string>",
    "article": "<string>",
    "clause": "<string>",
    "requirement_text": "<quoted excerpt>"
  },
  "policy_claim": "<quoted excerpt from policy>",
  "policy_section": "<section heading>",
  "behavioral_evidence": "<description of HAR finding or null>",
  "explanation": "<1-2 sentence plain English explanation>",
  "recommendation": "<what the site should change>"
}
```

### LLM Selection per Task

| Task | Model | Reason |
|---|---|---|
| Per-dimension scoring (bulk) | **Claude Haiku 4.5** | Fast, cheap, structured JSON output |
| Final report assembly | **Claude Sonnet 4.6** | Better reasoning for complex edge cases |
| Local / offline mode | **Llama 3.3 70B** (Ollama) | No API cost, self-hosted |
| Budget alternative | **Mistral 7B** (Ollama) | Lightweight, fast locally |

### Aggregated Report Output

```json
{
  "domain": "www.instagram.com",
  "scan_date": "2026-03-05",
  "overall_score": 42,
  "overall_verdict": "PARTIAL",
  "dimensions": [
    {
      "dimension": "pre_consent_tracking",
      "score": 12,
      "verdict": "FAIL",
      "breach": { "regulation": "GDPR", "article": "7", "clause": "7.1" },
      "behavioral_evidence": "Cookie '_fbp' set 340ms before consent",
      "recommendation": "Block all non-essential cookies until Accept is clicked"
    },
    {
      "dimension": "disclosure_of_third_parties",
      "score": 68,
      "verdict": "PARTIAL",
      "breach": { "regulation": "GDPR", "article": "13", "clause": "13.1.e" },
      "behavioral_evidence": "47 third-party domains observed, 12 not named in policy",
      "recommendation": "Add complete list of third-party data recipients to cookie policy"
    }
  ]
}
```

---

## 8. Implementation Steps

### Phase 1 — Compliance Document Loader `ingestion/compliance_loader.py`

1. Download GDPR, DPDP, CCPA, PECR as plaintext or PDF
2. Parse with `pdfplumber` or `PyMuPDF` (for PDFs) / direct text processing
3. Split by article using regex on legal structure (e.g. `Article \d+`, `Section \d+`)
4. Tag each chunk with full metadata (regulation, article, clause, requirement_type, severity)
5. Embed with `legal-bert-base-uncased` or `text-embedding-3-small`
6. Upsert to `compliance_docs` collection in vector DB
7. **Run once** — compliance docs don't change often

### Phase 2 — HAR Behavioral Extractor `ingestion/har_extractor.py`

This is a **runtime utility** — not a vector DB loader. It parses `.har` files on demand and returns structured behavioral evidence for injection into LLM prompts.

1. Load `.har` JSON from `telemetry_output/`
2. Extract all cookie-set events (`Set-Cookie` headers), sort by timestamp
3. Identify consent interaction timestamp from DOM events in `telemetry.json`
4. Flag cookies set before consent timestamp as `pre_consent_cookie`
5. Cross-reference third-party request domains against declared policy domains
6. Cross-reference cookie names against policy-declared cookie list
7. Return structured evidence dict (not upserted anywhere — used directly in prompt)

```python
# Usage at runtime
evidence = har_extractor.extract("telemetry_output/instagram.com_20260305.har",
                                  telemetry="telemetry_output/instagram.com_20260305_telemetry.json")
# Returns: {"pre_consent_cookies": [...], "third_party_domains": [...], ...}
```

### Phase 3 — Policy Text Reader `ingestion/policy_reader.py`

This is also a **runtime utility** — reads scraped policy markdown files from disk for direct injection into prompts.

1. Read `policy_documents/{domain}_privacy_policy.md` and `{domain}_cookie_policy.md`
2. Parse YAML front matter for metadata (domain, source_url, scraped_at, effective_date)
3. Return full text (for policies < 50K words) or section dict keyed by `## heading` (for long policies)

```python
# Usage at runtime
policies = policy_reader.load("www.instagram.com")
# Returns: {"privacy_policy": {"text": "...", "metadata": {...}},
#           "cookie_policy":  {"text": "...", "metadata": {...}}}
```

### Phase 4 — Scoring Pipeline `rag/scorer.py`

1. Define compliance dimensions (see Section 11)
2. Load policy text and HAR evidence for the target domain (phases 2 + 3 above)
3. For each dimension:
   a. Query `compliance_docs` vector DB for relevant law chunks (metadata filter by requirement_type)
   b. Select relevant HAR evidence events for this dimension from the runtime evidence dict
   c. Select relevant policy sections for this dimension (keyword filter or pass full text)
   d. Assemble context window: law chunks + policy text + HAR evidence
   e. Call LLM (Haiku) with structured scoring prompt
   f. Parse and store JSON response
4. Aggregate per-dimension scores → overall score (weighted by severity)

### Phase 5 — Report Builder `rag/report_builder.py`

1. Load all per-dimension scores
2. Call LLM (Sonnet) to write plain-English executive summary
3. Generate structured JSON report
4. Optionally: render HTML/PDF report using Jinja2 template
5. Save to `compliance_reports/{domain}_{date}_report.json`

### Phase 6 — Entry Point `compliance_report.py`

```bash
python3 compliance_report.py https://www.instagram.com \
    --telemetry telemetry_output/instagram.com_20260305_telemetry.json \
    --har telemetry_output/instagram.com_20260305.har \
    --regulations GDPR DPDP CCPA
```

---

## 9. Tool Options

### Embedding Models

| Model | Type | Cost | Notes |
|---|---|---|---|
| `nlpaueb/legal-bert-base-uncased` | Free, local | Free | Fine-tuned on legal text — best for compliance docs |
| `sentence-transformers/all-MiniLM-L6-v2` | Free, local | Free | Fast, good for policy text and HAR summaries |
| `sentence-transformers/all-mpnet-base-v2` | Free, local | Free | Higher quality than MiniLM, slower |
| `openai/text-embedding-3-small` | Paid API | ~$0.02/1M tokens | High quality, easy, no GPU needed |
| `openai/text-embedding-3-large` | Paid API | ~$0.13/1M tokens | Best quality, use for final production |
| `cohere/embed-english-v3.0` | Paid (free tier) | Free tier / ~$0.10/1M | Good with metadata-rich retrieval |

**Recommendation:**
- Compliance docs: `legal-bert-base-uncased` (understands "shall", "must", "data subject")
- Policy docs + HAR: `all-MiniLM-L6-v2` (fast, lightweight)
- Production: `text-embedding-3-small` across all collections (consistency, no GPU)

### LLM Options

| Model | Access | Cost | Notes |
|---|---|---|---|
| **Claude Haiku 4.5** | Anthropic API | ~$0.80/1M input tokens | Best for bulk per-dimension scoring |
| **Claude Sonnet 4.6** | Anthropic API | ~$3/1M input tokens | Best for final report, complex reasoning |
| **GPT-4o-mini** | OpenAI API | ~$0.15/1M input tokens | Cheap, good JSON output |
| **GPT-4o** | OpenAI API | ~$2.50/1M input tokens | Strong legal reasoning |
| **Llama 3.3 70B** | Ollama (local) | Free | Self-hosted, no API dependency |
| **Mistral 7B** | Ollama (local) | Free | Lightweight, fast on CPU |
| **Gemma 2 27B** | Ollama (local) | Free | Strong reasoning for local model |

### PDF/Document Parsing

| Tool | Type | Cost | Notes |
|---|---|---|---|
| `pdfplumber` | Python library | Free | Good text + table extraction |
| `PyMuPDF (fitz)` | Python library | Free | Faster, handles scanned PDFs less well |
| `pypdf` | Python library | Free | Lightweight, no binary dependencies |
| Adobe PDF Extract API | Paid API | Pay per page | Best quality, preserves structure |

### Orchestration

| Tool | Type | Notes |
|---|---|---|
| **LlamaIndex** | Python framework | Best for RAG pipelines and document indexing |
| **LangChain** | Python framework | Larger ecosystem, more complex |
| **Custom** | Pure Python | Simplest if staying within existing codebase style |

**Recommendation:** LlamaIndex — it has native support for chunking, metadata, multi-collection RAG, and structured output. Integrates directly with Chroma, Qdrant, and Pinecone.

---

## 10. File Structure

```
comp_square/
│
├── policy_scraper_2.py              ← Phase 1: website policy collection (DONE)
├── telemetry_collector.py           ← Phase 1: HAR + DOM telemetry (DONE)
├── llm_policy_assistant.py          ← Phase 1: LLM policy selection (DONE)
│
├── compliance_docs/                 ← Raw compliance regulation text
│   ├── gdpr_full.txt
│   ├── pecr_2003.txt
│   ├── dpdp_act_2023.txt
│   ├── ccpa_cpra.txt
│   └── hipaa_security_rule.txt
│
├── policy_documents/                ← Scraped website policies (DONE)
│   ├── www.instagram.com_privacy_policy.md
│   ├── www.instagram.com_cookie_policy.md
│   └── ...
│
├── telemetry_output/                ← HAR + telemetry files (DONE)
│   ├── instagram.com_20260305.har
│   ├── instagram.com_20260305_telemetry.json
│   └── ...
│
├── ingestion/                       ← document processing utilities
│   ├── __init__.py
│   ├── compliance_loader.py         ← parse + chunk compliance docs → vector DB (run once)
│   ├── policy_reader.py             ← read scraped .md files from disk → runtime context
│   └── har_extractor.py             ← parse .har + telemetry.json → runtime evidence dict
│
├── vectordb/                        ← vector DB client (compliance_docs only)
│   ├── __init__.py
│   ├── db_client.py                 ← Chroma / Qdrant setup + collection management
│   └── embedder.py                  ← embedding model wrapper (legal-bert)
│
├── rag/                             ← Phase 3: RAG + scoring
│   ├── __init__.py
│   ├── retriever.py                 ← hybrid retrieval per dimension
│   ├── scorer.py                    ← LLM scoring per dimension (Haiku)
│   ├── report_builder.py            ← aggregate scores → final report (Sonnet)
│   └── dimensions.py                ← compliance dimension definitions
│
├── compliance_reports/              ← output directory for reports
│   └── www.instagram.com_20260305_report.json
│
├── compliance_report.py             ← main entry point (CLI)
├── RAG_Pipeline_Architecture.md     ← this document
└── NextSteps.md
```

---

## 11. Compliance Dimensions Reference

These are the scoring dimensions the pipeline evaluates. Each maps to specific law articles and specific HAR evidence types.

| # | Dimension | Law Articles | HAR Evidence Type | Severity |
|---|---|---|---|---|
| 1 | **Pre-consent tracking** | GDPR Art 7, PECR Reg 6 | `pre_consent_cookie` | Critical |
| 2 | **Consent mechanism validity** | GDPR Art 7(1)(2) | `consent_interaction_log` | Critical |
| 3 | **Right to withdraw consent** | GDPR Art 7(3) | N/A (policy text only) | High |
| 4 | **Disclosure of data collected** | GDPR Art 13(1)(c) | `declared_vs_actual` | High |
| 5 | **Disclosure of third parties** | GDPR Art 13(1)(e) | `third_party_transfer` | High |
| 6 | **Cookie retention period** | GDPR Art 5(1)(e) | `long_retention` | High |
| 7 | **Cross-border data transfers** | GDPR Ch 5 (Art 44–49) | `third_party_transfer` | High |
| 8 | **Children's data protection** | GDPR Art 8, DPDP Art 9 | N/A (policy text only) | High |
| 9 | **Data subject rights disclosure** | GDPR Art 13(2)(b-f) | N/A (policy text only) | Medium |
| 10 | **Lawful basis stated** | GDPR Art 6, 13(1)(c) | N/A (policy text only) | Medium |
| 11 | **Tracking without consent** | PECR Reg 6 | `tracker`, `fingerprint` | Critical |
| 12 | **Data minimisation** | GDPR Art 5(1)(c) | `declared_vs_actual` | Medium |
| 13 | **Contact details of DPO/controller** | GDPR Art 13(1)(a)(b) | N/A (policy text only) | Low |
| 14 | **Policy effective date + versioning** | GDPR Art 13 (good practice) | N/A (policy text only) | Low |

---

*This document covers the full architecture from raw inputs to scored compliance reports. Implementation should proceed in order: Phase 1 (ingestion) → Phase 2 (vector DB) → Phase 3 (scoring) → Phase 4 (reporting).*
