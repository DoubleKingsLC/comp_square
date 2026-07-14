# Code Provenance — comp_square

**Author:** Aaron Joseph Jean — 25233118 · **Date:** 2026-07-13
Every module classified as: **written by me**, **adapted** (published methodology reimplemented, with source), or **reused as-is** (third-party artifact, with licence). Ends with why existing code was not used wholesale.

---

## 1. Written by me (original code)

| Module | What it does | Original elements |
|---|---|---|
| `telemetry_collector.py` | Playwright instrumentation: HAR recording, eTLD+1 third-party detection, fingerprinting trap script (canvas/WebGL/audio/WebRTC/battery/fonts), security headers, consent-UI tagging, policy-link extraction | Entire implementation. Fingerprint-hooking is a known *technique* (Englehardt & Narayanan 2016 describe the phenomenon); the trap script, alarm protocol, and JSON schema are mine |
| `policy_scraper_2.py` | Policy discovery (priority login-page scan, crawl, sitemap), link classification scoring, markdown + YAML front-matter export | Entire implementation |
| `llm_policy_assistant.py` | LLM-assisted policy link selection | Entire implementation |
| `ingestion/compliance_loader.py` | `LegalDocumentChunker`: regex chunking by legal unit (Article / UK-SI `6.—(1)` / Cal. Civ. `1798.100.`), metadata + requirement-type tagging | Entire implementation. "Chunk by legal unit, not tokens" is standard RAG practice; the multi-statute regex grammar and taxonomy are mine |
| `ingestion/ingest.py`, `vectordb/*` | HTML/PDF/text → chunks → embeddings → ChromaDB | Entire implementation (llama-index/Chroma as libraries) |
| `ingestion/har_extractor.py` | HAR + telemetry → structured behavioural evidence dict → prompt context | Entire implementation; detection *rule* adapted (below) |
| `rag/dimensions.py` | 15 compliance dimensions binding IRAC issue, law refs, retrieval query, evidence keys, severity | Mine; dimension coverage cross-checked against Xie et al.'s 34 clauses |
| `rag/retriever.py` | Metadata-filtered semantic retrieval + **dimension-anchored retrieval** (deterministic fetch of each dimension's known articles, merged ahead of semantic hits) | Entire implementation; anchoring mechanism is mine (devised after observing a GDPR Art 19 vs Art 13(1)(e) semantic near-miss) |
| `rag/scorer.py` | Prompt assembly, provider-agnostic LLM calls, response validation, severity-weighted aggregation, report JSON | Entire implementation; prompt *structure* adapted (below) |
| `ingestion/test_har_extractor.py` + fixtures | Regression tests | Mine |

## 2. Adapted — published methodology, my implementation

| Source | What was adopted | Where | Why reimplement (vs. run their code) |
|---|---|---|---|
| Trevisan et al., PoPETs 2019 (CookieCheck) | Profiling-cookie rule: third-party ∧ in **both** tracker lists ∧ lifetime ≥ 1 month; clean-profile no-interaction visit protocol | `har_extractor.py`, collector protocol | CookieCheck is 2017-era Docker+Chrome-DevTools tooling, unmaintained, measurement-only; we need per-site evidence dicts for LLM prompts, not aggregate violation statistics |
| Bouhoula et al., USENIX Sec 2024 (alsacnc) | "AA cookies" category definition (advertising+analytics); conservative tuning (prefer false negatives); banner-detection heuristics (EasyList Cookie + z-index) planned for collector upgrade | `har_extractor.py` (categories); backlog (banner interaction) | Their stack targets 97k-site crawls (Postgres, GPU ML pipeline, LibreTranslate); we audit single sites. We lift heuristics and rules, not infrastructure |
| Xiao et al., USENIX Sec 2023 (Lalaine) | Non-compliance typology: neglect / contrary / inadequate disclosure | `scorer.py` output schema (`discrepancy_type`) | Concept transfer only — their system is iOS binary/traffic analysis |
| Zimmeck et al., NDSS 2017 / MAPS 2019 | Closed set of practices checkable in both text and behaviour; "potential non-compliance" reporting language; cheap-model-first cost tiering | `dimensions.py` evidence-key binding; all report wording | Mobile static-analysis pipeline, not applicable to web |
| Ravichander et al., EMNLP 2019 (PrivacyQA) | Abstention: NOT_ADDRESSED verdict + confidence when policy is silent | `scorer.py` verdict schema | Dataset/finding, not a system |
| Guha et al., NeurIPS 2023 (LegalBench) | IRAC prompt framing (Issue–Rule–Application–Conclusion) | `scorer.py` SYSTEM_PROMPT | Benchmark, not a system; also planned for scorer-LLM selection |
| Xie et al., USENIX Sec 2025 | 34-clause systematisation (dimension coverage validation); expert-annotated per-clause F1 evaluation protocol | `dimensions.py`; evaluation plan | Policy-text-only pipeline; no behavioural evidence; no public artifact |

## 3. Reused as-is (third-party artifacts)

| Artifact | Use | Licence |
|---|---|---|
| Disconnect `services.json` | Tracker list A (categories) | GPLv3 (data use, unmodified) |
| Ghostery `trackerdb.json` (domains export) | Tracker list B (intersection rule) | CC-BY-NC-SA-4.0 — non-commercial academic use |
| llama-index, ChromaDB, sentence-transformers, Playwright, BeautifulSoup, pdfplumber | Framework libraries | OSS (MIT/Apache) |
| Planned: EasyList Cookie, OPP-115, PrivacyQA, LegalBench tasks, HttpArchive HARs | Banner detection; evaluation data | Respective public licences |

## 4. Why not use existing code wholesale?

1. **No existing system does the task.** The reviewed literature splits into policy-text analysis (no behaviour), web crawls (no policy cross-reference), and mobile static analysis (wrong platform). The core of comp_square — RAG triangulation of *law + notice + practice* for the live web — has no reference implementation to reuse.
2. **Granularity mismatch.** CookieCheck/alsacnc answer "what fraction of N sites violate?"; we answer "what exactly is this one site doing wrong, citing which article, contradicted by which policy sentence?" That requires structured per-site evidence, which their pipelines discard.
3. **Freshness/maintenance.** CookieCheck (2017) predates modern consent platforms; alsacnc pins a 2023-era Docker stack sized for a GPU crawl cluster.
4. **What we did instead** — adopted their *validated rules and definitions* (the scientifically load-bearing parts), cite them in code comments and in the paper, and implemented them inside our own pipeline where the LLM can consume their outputs.
