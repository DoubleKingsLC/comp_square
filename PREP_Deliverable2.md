# Deliverable 2 — Presentation Prep Guide

Three sections matching what you must be able to do: **(A)** explain every referenced paper, **(B)** explain every file of code, **(C)** defend every technical choice. Anticipated questions are marked **Q:**.

---

# A. The ten papers — what to know cold

For each: the pitch (say this first), the method (how they actually did it), the numbers (memorise bold ones), the limitation, and what we took.

## A1. Wilson et al. 2016 — OPP-115 (ACL)
**Pitch:** The founding dataset of automated privacy-policy analysis.
**Method:** **115** website policies manually annotated by law students (3 annotators each) into **23,000** fine-grained data practices across **10 categories** (first-party collection, third-party sharing, choice/control, retention, security, policy change, do-not-track, specific audiences, access/edit/delete, other). Trained SVM/logistic-regression classifiers to auto-categorise policy segments.
**Limitation:** shallow classifiers learn keyword associations, not meaning; text-only.
**We took:** the category taxonomy shaped our `requirement_type` metadata tags; the corpus is planned evaluation data.
**Q: why do you trust their taxonomy?** It was built by legal experts, is the field's de-facto standard (Polisis, PrivacyQA, MAPS and LegalBench all build on it), and survived a decade of reuse.

## A2. Harkous et al. 2018 — Polisis (USENIX Security)
**Pitch:** Deep learning replaces shallow classifiers for policy analysis.
**Method:** trained privacy-specific word embeddings on **130,000** policies, then a **hierarchical CNN** classifying each policy *segment* (**88.4%** top-level accuracy), powering the PriBot QA assistant.
**Limitation:** still text-only — high accuracy about *claims*, silent about *behaviour*.
**We took:** segment-level thinking (long policies get section-routed before scoring); their evidence that domain-specific embeddings beat general ones for *classification* — which we then found does NOT transfer to *retrieval* (see C7, the legal-BERT story).

## A3. Ravichander et al. 2019 — PrivacyQA (EMNLP)
**Pitch:** Even experts can't always answer questions from a policy — so systems shouldn't pretend to.
**Method:** **1,750** user questions about mobile-app policies, answered by legal experts as evidence-sentence selection; fine-tuned BERT baselines.
**Numbers:** large human–model gap; a substantial fraction of questions *unanswerable* from the policy; experts disagree with each other.
**We took:** the `NOT_ADDRESSED` verdict + confidence field — when the policy is silent and there's no behavioural evidence, the scorer abstains instead of forcing PASS/FAIL.
**Q: why does your scorer output confidence?** Because PrivacyQA showed disagreement is intrinsic to this task even among lawyers; a point estimate without confidence would overstate certainty.

## A4. Zimmeck et al. 2017 (NDSS) + MAPS 2019 (PoPETs)
**Pitch:** The first notice-vs-practice systems — proof the comparison can be automated.
**Method (2017):** policy text classifiers + **static analysis** of Android bytecode (API calls for location, identifiers, contacts) over **17,991** apps; flags collection the policy never discloses. **MAPS (2019):** scaled the same design to **1M+ apps** with a cheap-classifier-first pipeline.
**Limitation:** static analysis flags *dead code* (bundled-but-never-called libraries) → false positives; mobile-only; cannot see runtime consent state.
**We took:** (1) the design principle of a **closed set of practices checkable in BOTH text and behaviour** — that's why every behavioural dimension in `rag/dimensions.py` names its `evidence_keys`; (2) MAPS' "**potential** non-compliance" wording — we never assert legal conclusions; (3) cost tiering — small model for bulk scoring, big model reserved for report prose.

## A5. Xiao et al. 2023 — Lalaine (USENIX Security)
**Pitch:** Privacy labels lie — measured at scale, with a typology of *how* they lie.
**Method:** automated UI execution + **dynamic traffic capture** of **5,102** iOS apps, mapped observed data flows (data type, purpose, recipient) against Apple privacy labels.
**Numbers:** **3,423** non-compliant: **3,281 neglect** (undisclosed behaviour), **1,628 contrary** (label contradicts behaviour), **677 inadequate** (too vague).
**We took:** that exact typology is the `discrepancy_type` field in every scorer verdict. It turns "FAIL" into a *kind* of failure — much more useful in a report.

## A6. Trevisan et al. 2019 — CookieCheck (PoPETs) — *the ps.pdf paper*
**Pitch:** First large-scale measurement of cookie-law violations, with a conservative, defensible detection rule.
**Method:** CookieCheck = Docker-parallelised Chrome via DevTools Protocol; visit each site as a **fresh user, no clicks, no scrolling** (no implied consent), dump HAR, inspect Set-Cookie headers. **35,862** sites, **179,310** visits.
**The rule:** a *profiling cookie* = third-party ∧ domain in **both** Ghostery AND Disconnect tracker lists (intersection cuts false positives) ∧ lifetime **≥ 1 month** (empirical: 80% of tracker cookies last that long).
**Numbers:** **49%** of sites violate pre-consent (**86%** news/media, **14%** law/government); violations invariant to browser, device and client country; only **7%** of banner-showing sites actually wait for consent.
**Limitation:** ignores policy text entirely; misses JS-set cookies (only Set-Cookie headers).
**We took:** the profiling-cookie rule verbatim into `har_extractor.py`; the clean-profile visit protocol; single-vantage scanning justified by their invariance result. We *fixed* their JS blind spot by merging Playwright context cookies.

## A7. Bouhoula et al. 2024 — alsacnc (USENIX Security)
**Pitch:** First general (CMP-independent) automated audit of cookie *notices*, including what happens when you reject.
**Method:** crawler on **~97k** EU sites; banner detection via EasyList Cookie filter list + z-index heuristics; DFS through banner settings; actions tested: accept / reject / save-defaults / close / nothing. Three ML models: declared-purpose BERT (**97.6%**), interactive-element BERT (**95.1%**), CookieBlock XGBoost classifying cookie purpose **from cookie features, no tracker list** (P **98.7** / R **91.9**). A decision tree maps observations → violation types; everything tuned conservative (prefer false negatives).
**Number to quote:** **65.4%** of sites offering a reject option still collect data after explicit rejection.
**We took:** the AA-cookie (advertising+analytics) category definition for our Ghostery filter; conservative-tuning philosophy; their open-source banner heuristics are the plan for our collector's consent-interaction upgrade.

## A8. Guha et al. 2023 — LegalBench (NeurIPS)
**Pitch:** The benchmark proving LLMs can do rule-application legal reasoning.
**Method:** **162** tasks from **40** contributors, organised by the **IRAC** framework (Issue → Rule → Application → Conclusion); includes OPP-115-derived privacy tasks.
**We took:** IRAC is literally our prompt structure: Issue = compliance dimension, Rule = retrieved article text, Application = policy + telemetry facts, Conclusion = verdict JSON. Also our planned scorer-LLM selection benchmark.

## A9. Xie et al. 2025 (USENIX Security)
**Pitch:** LLM-vs-codified-law works at scale — on text alone.
**Method:** systematised **10** privacy laws into **34 clauses** across **4 themes**; LLM pipeline evaluated policies of **100k+** sites; validated against expert-annotated samples.
**Numbers:** per-clause **F1 ≥ 0.84, average 0.94**.
**Limitation (their own):** no runtime behavioural evidence — exactly our gap.
**We took:** their 34 clauses validate our 15 dimensions' coverage; their expert-annotation + per-clause-F1 protocol *is* our evaluation design.

## A10. The synthesis sentence (memorise)
"Each direction masters one modality — policy text, mobile behaviour, web behaviour, or legal reasoning — but none integrates the three sources a compliance judgement needs: the **law**, the **notice**, and the **practice**. comp_square triangulates all three for the dynamic web."

---

# B. The code — file by file, in pipeline order

Practice by opening each file and saying the bold sentence, then the details.

## B1. `telemetry_collector.py` (~630 lines)
**"This captures the *practice* — what the site actually does on a first visit."**
- Playwright Chromium, clean context per run → HAR recorded natively (`record_har_path`).
- `get_etld1()` / `is_third_party()`: registrable-domain comparison (handles co.uk etc.) — a request/cookie is third-party if its eTLD+1 differs from the site's.
- `FINGERPRINT_TRAP_SCRIPT`: injected *before* page scripts; monkey-patches canvas `toDataURL`, WebGL context, AudioContext, RTCPeerConnection, `getBattery`, font checks, geolocation, clipboard — each access logs a `COMPLIANCE_ALARM` to the console, which we harvest.
- Consent-UI tagging: every button/link scored against consent tokens ("accept", "reject", "manage"...) → `consent_related` flags.
- No clicking/scrolling — Trevisan's protocol: everything captured is pre-consent by construction.
- Output: `.har`, `_telemetry.json`, `_dom.html`, screenshot.

## B2. `policy_scraper_2.py`
**"This captures the *notice* — the site's written promises."**
- Discovery: telemetry policy links + homepage/login-page crawl + sitemap; candidate links scored by keyword heuristics; privacy + cookie policies fetched and exported as markdown with YAML front matter (source URL, scrape time).
- Known limitation to admit proactively: prefers same-domain URLs; independent.ie hosts policies on parent mediahuis.ie → cross-domain fix on backlog.

## B3. `ingestion/compliance_loader.py`
**"This turns statutes into retrievable, citable units — the *law*."**
- `LegalDocumentChunker`: regex splits on legal-unit headings — `Article 7` (GDPR/DPDP), `6.—(1)` (UK SI / PECR), `1798.100.` (California Civil Code). One chunk = one article ⇒ citations stay valid.
- Heading-only fragments (<120 chars, e.g. GDPR's internal "Section 1" headers) dropped — that fix took GDPR from 114 noisy chunks to **exactly 99, one per article**.
- Each chunk tagged: regulation, jurisdiction, article, `requirement_type` (keyword heuristic; children checked before consent so Art 8 tags correctly), severity.

## B4. `ingestion/ingest.py` + `vectordb/`
- Reads text/PDF (pdfplumber)/HTML (BeautifulSoup, added when we got real statute files), normalises headings, chunks, embeds, upserts to ChromaDB collection `compliance_docs`.
- Embeds **clause text only** (`metadata_mode="none"`) so node and query embeddings live in the same distribution.
- `vectordb/embedder.py`: `all-mpnet-base-v2` (see C7 for the story), env-overridable.

## B5. `ingestion/har_extractor.py` (~500 lines)
**"This converts a raw HAR into structured, conservative evidence an LLM can cite."**
- Walks HAR entries; parses every `Set-Cookie` (name, domain, lifetime from Max-Age/Expires).
- **Trevisan rule:** `profiling = third_party ∧ tracker-listed ∧ lifetime ≥ 30 days`. Tracker check has three modes — `intersection` (Disconnect ∩ Ghostery, strictest), `single-list`, `builtin-fallback` (~55 bundled domains, offline) — the active mode is recorded in the output so the LLM knows how strict the classification was.
- Merges telemetry context cookies to catch **JS-set** cookies HAR headers miss (deduped) — fixes CookieCheck's admitted blind spot.
- `declared_vs_actual`: observed third-party domains minus policy-declared ones → Lalaine `neglect`.
- `to_prompt_context()`: renders the evidence block injected into prompts, including the AUDIT PROTOCOL NOTE.
- `--update-lists` downloads both tracker lists; `test_har_extractor.py` = offline regression suite (inclusions, exclusions, dedup, typology).

## B6. `rag/dimensions.py`
**"The closed set of things we check — each bound to its law and its evidence."**
- 15 dimensions; each has: IRAC issue question, `law_refs` (parsed into retrieval anchors), semantic `retrieval_query`, `requirement_type` filter, `evidence_keys` (8 behavioural, 7 policy-only — Zimmeck's principle), severity → weights (critical 3, high 2, medium 1, low 0.5).

## B7. `rag/retriever.py`
**"Gets the right article in front of the LLM — deterministically where possible."**
- Semantic search over ChromaDB with metadata filters (requirement_type, regulation), fallback to unfiltered if empty.
- **Dimension-anchored retrieval** (`retrieve_for_dimension`): parses `law_refs` ("GDPR Art 13" → `('GDPR','13')`), fetches those articles by exact metadata match, puts them *ahead* of semantic hits, dedupes. Born from a real failure: cosine similarity ranked GDPR Art 19 ("communicate to recipients...") above Art 13(1)(e) ("disclose recipients") for the third-party-disclosure dimension.

## B8. `rag/scorer.py` (~400 lines)
**"The judge: assembles law + notice + practice per dimension, gets a structured verdict."**
- SYSTEM_PROMPT: IRAC method; scoring rubric (0–24 clear violation w/ evidence … 75–100 compliant); verdicts PASS/FAIL/PARTIAL/**NOT_ADDRESSED**; Lalaine `discrepancy_type`; **Evidence discipline** rules (cite only listed events; empty evidence ⇒ no behavioural violation; the crawler's no-interaction protocol is never itself a violation) — added after the over-condemnation incident.
- `select_evidence()`: only the dimension's `evidence_keys` are rendered — the model never sees irrelevant evidence to misuse.
- `call_llm()`: provider inferred from model name (claude-* → Anthropic, gpt-* → OpenAI with JSON mode); **temperature 0**.
- `parse_response()`: strips fences, extracts JSON, clamps score/confidence, validates verdict enum — bad output degrades to an ERROR verdict, never a crash.
- `aggregate()`: severity-weighted mean, NOT_ADDRESSED excluded; report JSON with disclaimer → `compliance_reports/`.
- `--dry-run` prints assembled prompts with no API key or DB — how we inspect exactly what the model sees.

---

# C. Technical choices — anticipated Q&A

**C1. Q: Why Playwright and not Selenium or OpenWPM?**
Native HAR recording, init-scripts injected before page JS (essential for fingerprint traps), reliable headless Chromium, async API. OpenWPM (used by Englehardt et al.) is a heavier research harness geared to crawls; Trevisan likewise judged it overkill and built lighter tooling — same reasoning.

**C2. Q: Why HAR files as the evidence format?**
Standard (used by Trevisan and by HttpArchive's public dataset — free test data), complete (every request/response incl. Set-Cookie), and produced natively by both Playwright and browser DevTools, so evidence is reproducible by anyone.

**C3. Q: Why the intersection of two tracker lists?**
Trevisan's rule: intersection minimises false positives — one list's mistake doesn't condemn a domain. We prefer false negatives (missing a violation) over false accusations; every classification also records which mode was active.

**C4. Q: Why lifetime ≥ 30 days?**
Empirical, from Trevisan's CDF: 80% of tracker cookies live ≥ 1 month; short-lived cookies are usually functional. Citable threshold rather than an arbitrary one.

**C5. Q: Why chunk statutes by article instead of fixed token windows?**
Legal meaning lives in the article unit; token windows split clauses mid-sentence and make citations invalid. A verdict must cite "GDPR Art 7(1)" and quote it — only possible if the chunk *is* the article. Cost: variable chunk sizes; acceptable because statutes' articles fit embedding limits.

**C6. Q: Why ChromaDB?**
Zero-infrastructure local persistence, native metadata filtering (we filter on regulation/article/requirement_type — load-bearing for anchored retrieval), first-class llama-index support. Qdrant is the documented production upgrade path; the interface (`vectordb/db_client.py`) isolates that swap.

**C7. Q: Why all-mpnet-base-v2 and not legal-BERT? (the best story — tell it even if not asked)**
We *started* with legal-BERT for its legal vocabulary. Measured result: near-uniform similarities (~0.72 for everything) — a cookie-consent query ranked DPDP *penalty* clauses above GDPR Art 7. Diagnosis: legal-BERT is a raw masked-LM checkpoint, not sentence-trained; mean-pooled raw BERT embeddings are notoriously anisotropic. Switched to a sentence-trained encoder → Art 7 top-ranked with clean separation. Lesson for the paper: domain vocabulary does not compensate for missing sentence-level training. It's overridable by env var, and fine-tuning legal-BERT with sentence objectives is documented future work.

**C8. Q: Why RAG at all — why not just prompt GPT-4 with "check this against GDPR"?**
Three reasons: hallucinated citations (ungrounded models invent article numbers); auditability (we can show the exact retrieved text behind every verdict); and controllability — proven by our error analysis: when a wrong article was cited, the bug was *findable in the retriever* and fixable deterministically. Grounding moves failures from generation (opaque) to retrieval (debuggable).

**C9. Q: Why not fine-tune a model instead?**
No training data exists for law+notice+practice triangulation (that's the gap); fine-tuning freezes legal knowledge (laws change — swap the vector store, not the model); and a capstone budget favours retrieval + prompting, which Xie et al. showed reaches F1 0.94 on the text side without fine-tuning.

**C10. Q: Why gpt-4o-mini? Why is the scorer provider-agnostic?**
Bulk scoring = 15 calls/site; needs cheap, fast, strict JSON (JSON mode guarantees parseability). Provider inferred from model name so Claude Haiku/Sonnet are drop-ins — the architecture is the contribution, not the vendor. Formal selection: LegalBench privacy tasks + our labelled sample, F1 per dollar.

**C11. Q: Why temperature 0?**
Reproducibility. Scores that change between identical runs are useless for evaluation and for before/after comparisons like our prompt-fix verification.

**C12. Q: Why IRAC prompt structure?**
It's how lawyers structure rule-application (LegalBench organises 162 tasks by it), and it maps 1:1 onto our data: Issue = dimension, Rule = retrieved article, Application = policy + telemetry, Conclusion = verdict. It also forces the model to separate rule from facts — the failure mode we then guard with "cite only the Rule text".

**C13. Q: How do you know the LLM's verdicts are right?**
We don't assume it — we caught it wrong twice. (1) Over-condemnation: FAIL@confidence-1.0 with fabricated cookie evidence → fixed with evidence-discipline guards; re-run flipped to PARTIAL with policy-only reasoning. (2) Wrong article via retrieval near-miss → fixed with dimension-anchored retrieval. Both documented before/after in PROGRESS.md. Formal evaluation: hand-annotated sample, per-dimension F1 (Xie protocol).

**C14. Q: Why the NOT_ADDRESSED verdict?**
PrivacyQA: even legal experts find questions unanswerable from a policy. Forcing PASS/FAIL on silence manufactures false certainty; NOT_ADDRESSED + low confidence is honest and excluded from the aggregate.

**C15. Q: Why severity weights 3/2/1/0.5?**
Ordinal encoding of legal risk (pre-consent tracking is a headline GDPR-fine category; a missing effective-date is a formality). The exact values are a stated assumption — sensitivity analysis is listed future work.

**C16. Q: Why is all output "potential" non-compliance?**
MAPS convention: an automated tool provides evidence for lawyers, not legal conclusions. Also honest: our detectors are deliberately conservative.

**C17. Q: Why didn't you just run CookieCheck or alsacnc?**
Different question and different granularity: they answer "what fraction of N sites violate?"; we answer "what is *this* site doing wrong, under which article, contradicted by which policy sentence?" — that needs per-site structured evidence their pipelines discard. CookieCheck is 2017-era unmaintained tooling; alsacnc is crawl infrastructure (Postgres+GPU stack). We adopt their validated *rules* with citations and implement them in our pipeline. (Full argument: CODE_PROVENANCE.md.)

**C18. Q: What are the known limitations?**
Policy scraper struggles with cross-domain hosting (mediahuis case) and bot-walled sites; no consent-interaction yet (accept/reject diffing is next — Bouhoula heuristics); DPDP PDF chunks are noisy; single annotator for evaluation ground truth (acknowledged, PrivacyQA-style); LLM verdicts on policy-only dimensions depend on scraped-policy completeness.

**C19. Q: What's novel here?**
The triangulation itself (no prior system feeds live web telemetry + policy + retrieved law to an LLM), dimension-anchored retrieval as a grounding mechanism, the JS-set-cookie recovery over CookieCheck's method, and (planned, novel) post-login consent-scope auditing.

**C20. Q: Independent.ie found 0 profiling cookies but you still failed it — contradiction?**
No — the interesting nuance: the CMP *held cookies* correctly (0 profiling cookies under the strict rule, scored PARTIAL not FAIL) but tracker *requests* to doubleclick/taboola/GA and fingerprinting API calls still fired pre-consent — a distinction a cookie-only audit (CookieCheck) cannot see and our telemetry can. That's the pipeline discriminating, not blanket-condemning.

---

# Two-day plan

**Day 1 AM:** Section A — one pass reading, then explain each paper aloud in 60 seconds from just its bold pitch line. **Day 1 PM:** Section B with the repo open — actually run `--dry-run` and `test_har_extractor.py` while narrating; run the universityofgalway.ie comparison for a fresh result.
**Day 2 AM:** Section C aloud, ideally with someone firing the Q's at random. **Day 2 PM:** full 20-min run-through with the deck twice; the speaker notes carry the numbers if you blank.
