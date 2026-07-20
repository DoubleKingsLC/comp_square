# comp_square — Progress Log

Chronological record of implementation work. Newest first.

---

## 2026-07-19 — Report frontend (Phase 5)

- `rag/report_builder.py`: renders scorer JSON as a **self-contained HTML report** (inline CSS, no JS/server — opens offline). Header with overall score + verdict, per-dimension cards sorted worst-first (verdict badge, score bar, article quote, policy claim, behavioural evidence, Lalaine discrepancy label, recommendation, confidence), optional behavioural-evidence appendix via `--evidence`, disclaimer + protocol footer.
- Generated `compliance_reports/www.independent.ie_20260712_report.html` from the real scored run — demo flow for the presentation: run scorer CLI → open HTML.

## 2026-07-13 — Deliverable 2 materials

- `Deliverable2_Supervisor_Update.pptx` — 14 slides + speaker notes for the 20-min update. Structured to answer the last meeting's criticisms head-on: per-paper depth with adopted elements (slides 3–4 + notes), gaps→design (5), model choices with empirical justification (7), code provenance + why-not-existing-code (8), live results (10), error analysis before/after (11), evaluation plan (12).
- `CODE_PROVENANCE.md` — module-by-module: written-by-me / adapted (methodology, cited) / reused as-is (licensed), plus the why-not-existing-code argument.

---

## 2026-07-12 — Literature integration + HAR evidence extractor

### Literature review paper (`literature_review_ieee.tex`)
- Reviewed all 10 cited papers for reusable techniques, code, and datasets (full analysis in `Implementation_Pointers.md`).
- Added *"Adopted in our framework"* paragraphs to each of the four review subsections (II-A–II-D), stating what each paper contributes to the implementation.
- Added new subsection III-C *"Techniques and Artifacts Adopted from Reviewed Work"* with Table IV mapping every reference → adopted element → framework component.
- Recompiled cleanly: 6 pages, no undefined citations. Output: `literature_review_ieee_updated.pdf`.

### New: `Implementation_Pointers.md`
- Per-paper borrow list with artifact links (alsacnc crawler, OPP-115, PrivacyQA, LegalBench, Xie 2025) and a 7-day sprint order.

### New: `ingestion/har_extractor.py` (runtime evidence utility)
- Parses Playwright `.har` + matching `*_telemetry.json` → structured behavioral evidence dict + `to_prompt_context()` text block for the RAG scorer.
- **Profiling-cookie rule** (Trevisan et al., PoPETs 2019): third-party ∧ tracker-listed ∧ lifetime ≥ 30 days. Three strictness modes: `intersection` (Disconnect ∩ Ghostery trackerdb), `single-list`, `builtin-fallback` (~55 bundled tracker domains, works offline). Mode is recorded in the evidence output.
- **Pre-consent by construction**: collector performs no banner interaction (Trevisan clean-profile protocol), so all observed cookies are pre-consent.
- **JS-set cookie recovery**: merges telemetry context cookies with HAR `Set-Cookie` events (deduped) — catches `_ga`-style JS cookies that HAR headers miss.
- **Declared-vs-actual** comparison with Lalaine (USENIX 23) discrepancy typology (`neglect` implemented; `contrary`/`inadequate` reserved for the LLM scorer).
- Conservative reporting: all findings phrased as *potential* violations (MAPS convention).
- `--update-lists` CLI flag downloads/refreshes tracker lists into `ingestion/data/`.
- *Fix (same day):* Ghostery trackerdb URL corrected to the release asset (`releases/latest/download/trackerdb.json` — the old repo-tree path 404'd); parser now filters pattern domains to advertising/analytics categories (Bouhoula "AA cookies" definition). Ghostery trackerdb is CC-BY-NC-SA-4.0 — fine for academic use.

### New: `ingestion/test_har_extractor.py`
- Self-contained regression test (synthetic HAR + telemetry fixtures, no network). Covers: rule inclusions/exclusions (non-tracker third party, short-lived tracker cookie, first-party session), JS-set dedup, Lalaine neglect detection, HAR-only path, prompt rendering. **Status: passing.**

### Verified on real data (2026-07-12, local run)
- `--update-lists`: Disconnect + Ghostery trackerdb downloaded; 3,311 secondary AA domains → **intersection mode** active.
- Overleaf HAR (2026-03-03 capture): no pre-consent profiling cookies, consent UI detected, 2 third-party domains (gstatic.com, recaptcha.net — correctly not classed as trackers). Plausibly compliant result; conservative rule not over-firing.
- facebook.com (2026-03-03 capture): no pre-consent profiling cookies (Meta cookies are first-party; fbcdn/instagram are Meta CDNs, not listed trackers). **4 WebGL fingerprinting alarms** — evidence for `tracking_without_consent`.
- independent.ie (fresh 2026-07-12 scan): consent UI (Didomi, privacy-center.org) detected; doubleclick/GA/googlesyndication/taboola/cxense **contacted** but no cookies set pre-consent — consistent with Google consent-mode cookieless pings, i.e., a plausibly compliant CMP setup. 4 fingerprinting alarms (3× WebRTC likely from the agnoplay video player — possible benign use; 1× battery API).
- *Fixes from this run:* (1) eTLD+1 bug — `api.kaching.eu.com` collapsed to `eu.com`; added private public-suffix registries (eu.com, us.com, uk.com, …) to `MULTI_TLDS` in both har_extractor and telemetry_collector. (2) `to_prompt_context()` now lists tracker-listed domains *contacted* even when no cookie is set (request-level collection, Bouhoula-style; also surfaces consent-mode behaviour to the LLM).

---

## 2026-07-12 (later) — RAG scorer package (`rag/`)

### New: `rag/dimensions.py`
- 15 compliance dimensions (the 14 from the architecture doc §11 + `security_headers`), each with: IRAC issue statement, law refs, `requirement_type` retrieval filter, semantic retrieval query, `evidence_keys` binding to `har_extractor` output (Zimmeck closed-set principle — 8 behavioural, 7 policy-only), severity + weights (critical 3 / high 2 / medium 1 / low 0.5).

### New: `rag/retriever.py`
- Retrieves law chunks from ChromaDB `compliance_docs` via the existing `vectordb/` helpers (legal-BERT + llama-index). Metadata filter on `requirement_type` (+ optional regulation), automatic fallback to unfiltered search if the filter returns nothing. `render_law_context()` formats the IRAC "Rule" block.

### New: `rag/scorer.py`
- IRAC-structured prompt (LegalBench): Issue = dimension, Rule = retrieved article text only ("never cite from memory"), Application = policy (notice) + HAR evidence (practice), Conclusion = JSON verdict.
- Verdicts: PASS / FAIL / PARTIAL / **NOT_ADDRESSED** + confidence (PrivacyQA); `discrepancy_type` neglect/contrary/inadequate (Lalaine); all output framed as *potential* violations (MAPS).
- Robust response parsing (fence-stripping, range clamping, graceful ERROR verdict), severity-weighted aggregation excluding NOT_ADDRESSED, report JSON → `compliance_reports/`.
- `--dry-run` prints assembled prompts with no API key or vector DB needed.
- Tested offline: dimension definitions, parse/validate paths, aggregation math, evidence selection against the har_extractor fixture, full dry-run prompt assembly. **Passing.**
- Not yet tested (needs local venv + API key): live retrieval against ChromaDB and a real Haiku scoring run.

---

## 2026-07-12 (later) — Ingestion upgrades for real regulation files

- Verified downloaded sources: `gdpr_full.html` (EUR-Lex OJ L 119) ✓, `pecr_2003.xhtml` (legislation.gov.uk) ✓, `ccpa_cpra.html` ✗ **wrong doc** (bill AB-1542, not the codified CCPA — re-download from leginfo Civil Code §1798.100 title 1.81.5).
- `ingestion/ingest.py`: added `.html/.xhtml/.htm` support (BeautifulSoup text extraction + heading normalization).
- `ingestion/compliance_loader.py`: chunker regex extended for PECR UK-SI numbering (`6.—(1)`) and CCPA Civil Code numbering (`1798.100.`); heading-only fragments (<120 chars, e.g. GDPR's internal "Section N" headings and TOC lines) dropped; `children` requirement-type check moved before `consent`.
- Verified against the real files: **GDPR → exactly 99 chunks (Art 1–99, no dups, none missing); PECR → 54 chunks, Reg 6 correctly captured** (schedule paragraph numbering causes benign duplicate ids — future refinement).
- Reminder: reset the Chroma collection before full ingest (old `test_gdpr` chunks pollute retrieval; `vector_store.add` has no dedup).

---

## 2026-07-12 (later) — Embedder fix after first live retrieval test

- **Finding (worth reporting in the paper):** `nlpaueb/legal-bert-base-uncased` is a raw BERT checkpoint, not a sentence-embedding model. Mean-pooled it produced near-uniform similarities (~0.72 for everything) and effectively random retrieval — a cookie-consent query ranked DPDP penalty/appeals clauses above GDPR Art 7 / PECR Reg 6. Domain vocabulary does not compensate for missing sentence-level training.
- `vectordb/embedder.py`: default switched to `sentence-transformers/all-mpnet-base-v2` (overridable via `EMBED_MODEL` env var); legal-BERT kept as a documented option for fine-tuning experiments.
- `ingestion/ingest.py`: nodes now embedded with `metadata_mode="none"` — clause text only, matching the plain-text query distribution (metadata still stored for filters/citations).
- `test_query.py` default top_k 2 → 4.
- Requires collection reset + re-ingest (embedding space changed).

---

## 2026-07-12 (later) — FIRST END-TO-END SCORING RUN ✅

- Full pipeline executed on www.independent.ie: ChromaDB law retrieval (GDPR+PECR) + scraped Mediahuis cookie policy + HAR/telemetry evidence → LLM scoring (gpt-4o-mini via new provider-agnostic `call_llm`; OpenAI JSON mode).
- Results: pre_consent_tracking FAIL (0, conf 1.0) · tracking_without_consent FAIL (10, conf 0.9) · disclosure_of_third_parties PARTIAL (25, conf 0.7) → overall 10/100 POTENTIAL_NON_COMPLIANCE.
- `rag/scorer.py`: added OpenAI support (provider inferred from model name; claude-* → Anthropic, gpt-* → OpenAI with `response_format=json_object`).
- Fixed Python 3.9 crash: missing `from __future__ import annotations` in `rag/dimensions.py` / `rag/retriever.py`.
- Environment: playwright browser build mismatch resolved (`python3 -m playwright install chromium` — venv CLI, not system PATH).
- Policy note: independent.ie hosts policies on parent domain mediahuis.ie (cookie policy explicitly lists Independent.ie in scope). Scraper's same-domain preference 404'd — cross-domain policy-link handling added to backlog. Privacy statement still to be captured.
- **Verified (report review):** tracking_without_consent FAIL was correct (pre-consent tracker requests + fingerprinting); disclosure_of_third_parties PARTIAL was correct (vague policy clause quoted, unnamed recipients). pre_consent_tracking FAIL@1.0 was **over-condemnation**: the model (a) invented cookie installations not present in the evidence, and (b) misread our "consent interaction: none" protocol line as the site lacking a consent mechanism.
- **Prompt fixes (2026-07-13):** evidence block reworded ("AUDIT PROTOCOL NOTE: crawler deliberately performs no consent interaction — not a site failing"); empty-evidence guard ("absence of observed events ⇒ MUST NOT assert behavioural violation"); system-prompt "Evidence discipline" section (cite only listed events, never infer). This before/after is documented evaluation material for the paper.
- **Re-run confirmed (2026-07-13):** pre_consent_tracking flipped FAIL(0)→PARTIAL(50) with `behavioral_evidence: null` and policy-text-only reasoning — prompt guards effective. tracking_without_consent held FAIL (headline finding: pre-consent tracker requests + fingerprinting).
- **New issue found & fixed:** disclosure_of_third_parties cited GDPR Art 19 (rectification notification) instead of Art 13(1)(e) — semantic near-miss by the retriever, not the LLM. Fix: **dimension-anchored retrieval** (`retrieve_for_dimension` in rag/retriever.py) — each dimension's known articles (parsed from `law_refs`) are fetched deterministically by metadata and placed ahead of semantic results; verified anchors parse for all 15 dimensions.
- Reproducibility: `temperature=0` set for both providers.

---

## 2026-03-05 — RAG pipeline architecture (design)
- `RAG_Pipeline_Architecture.md` finalized: pre-loaded compliance docs in vector DB; policies + HAR as runtime inputs; 14 compliance dimensions; Haiku per-dimension scoring, Sonnet report assembly.
- `Ingestion_Architecture.md`: Layer-1 flow (LegalDocumentChunker → legal-BERT → ChromaDB `compliance_docs`), `ingestion/ingest.py` + `test_query.py` working.

## 2026-03-03/04 — Telemetry collector v3.0
- `telemetry_collector.py`: Playwright HAR recording, eTLD+1 third-party detection, fingerprinting trap script (canvas/WebGL/audio/WebRTC/battery/fonts), security headers + SSL, consent-UI element tagging, policy-link extraction, batch CLI.
- Sample captures collected: facebook.com (×2), overleaf.com.

## Earlier — Phase 1
- `policy_scraper_2.py`: policy discovery + markdown export with YAML front matter.
- `llm_policy_assistant.py`: LLM-assisted policy link selection.

---

# Roadmap / Backlog

## Next (current sprint)
1. `rag/scorer.py` — IRAC prompt structure (LegalBench), `NOT_ADDRESSED` verdict + confidence (PrivacyQA), `discrepancy_type` (Lalaine), "potential violation" wording (MAPS)
2. Consent-banner interaction in `telemetry_collector.py` — accept/reject/no-interaction protocol, EasyList Cookie + z-index detection (Bouhoula et al., alsacnc)
3. `rag/dimensions.py` — validate 14 dimensions against Xie et al.'s 34 clauses; per-dimension F1 evaluation on a hand-labeled sample

## Backlog (noted 2026-07-12)
- **Post-login observation** *(Aaron's request — parked for now)*: after consent state is recorded, authenticate with a test account and capture a second HAR/telemetry pass to compare **what is actually collected while logged in vs. what was consented to**. Design notes:
  - Extends the accept/reject protocol with a third state: `consented(post-login)` — diff cookies/requests across states (Trevisan Fig. 7 method, applied to authenticated sessions).
  - Needs credential handling (env vars, never committed), per-site login scripts, and bot-detection mitigations.
  - Evidence types to add: `post_login_collection`, `consent_scope_exceeded` (data flows present after login that no consent covers).
  - Maps to GDPR Art 7(1) (scope of consent) + Art 13 (disclosure at collection time) — strong differentiator, no reviewed paper does this for the web.
- Ghostery/Disconnect list refresh automation (cron or pre-scan check).
- Multi-visit scans (5 visits/site, Trevisan) for cookie stability.
