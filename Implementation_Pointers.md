# Implementation Pointers — What to Borrow from Each Reviewed Paper

Maps all 10 literature-review papers to concrete comp_square components. Priorities are set for a one-week build sprint.

---

## [1] Trevisan et al. 2019 — "4 Years of EU Cookie Law" (PoPETs)

**What we learn:** Conservative, defensible violation detection: a *profiling cookie* = third-party + domain in **both** Ghostery AND Disconnect tracker lists + lifetime ≥ 1 month. Measurement protocol: fresh profile, no scrolling/clicking (avoids implied consent), wait for OnLoad or timeout, dump HAR, 5 visits per site. Location/browser don't change results — one scan location suffices. Baselines: 49% violation rate overall, 86% News/Media, top-10 trackers ≈ 40% of violations.

**Borrow:**
- CookieCheck (open source): Docker-parallelized Chrome via DevTools Protocol
- Ghostery ∩ Disconnect intersection rule + 1-month lifetime threshold
- HttpArchive public dataset — free HARs for testing `har_extractor.py` without crawling
- Consent before/after diff (save profile post-Accept, revisit, diff cookies)

**Goes into:** `ingestion/har_extractor.py` (profiling-cookie rule), `telemetry_collector.py` (multi-visit, no-interaction protocol), evaluation baseline numbers for the report.
**Priority: HIGH — implement the profiling-cookie rule first.**

---

## [2] Bouhoula et al. 2024 — "Automated Large-Scale Analysis of Cookie Notice Compliance" (USENIX Sec 24)

**What we learn:** First general (CMP-independent) consent audit of 97k EU sites. Banner detection = EasyList Cookie filter list + z-index heuristic + sentence segmentation. Crawler navigates banner settings via DFS and tests actions: accept / reject / save defaults / close / no interaction. Three ML models: declared-purpose BERT (97.6%), interactive-element BERT (accept/reject/close/save/settings, 95.1%), and CookieBlock XGBoost classifying **observed cookie purpose from cookie features** (precision 98.7% / recall 91.9%) — no tracker list needed. A decision tree maps model outputs → 10 violation/dark-pattern types. Key finding: 65.4% of sites offering rejection likely collect data despite explicit negative consent. Models tuned conservative (prefer false negatives).

**Borrow:**
- Code: https://github.com/bouhoula/alsacnc — `cookie_crawler/commands` (banner detect/explore), `cookie_crawler/scripts` (injected JS), `classifiers/`
- EasyList Cookie list: https://secure.fanboy.co.nz/fanboy-cookiemonster.txt
- CookieBlock cookie-purpose classifier as a tracker-list-independent second signal
- Decision-tree violation taxonomy → our dimension verdict rules
- "Reject-then-observe" test — strongest violation evidence there is

**Goes into:** `telemetry_collector.py` (banner detection + accept/reject interaction — currently your NextSteps gap), `ingestion/har_extractor.py` (cookie-purpose classification), `rag/dimensions.py` (violation taxonomy).
**Priority: HIGH — banner interaction is the biggest capability gap vs. state of the art.**

---

## [3] Wilson et al. 2016 — OPP-115 (ACL)

**What we learn:** 115 policies, 23k practices annotated by law students into 10 data-practice categories (First-Party Collection, Third-Party Sharing, Choice/Control, Retention, Security, Policy Change, Do Not Track, Specific Audiences, Access/Edit/Delete, Other). Shallow classifiers plateau — motivates LLMs.

**Borrow:** The category taxonomy (validate/extend our `requirement_type` metadata) and the corpus (https://usableprivacy.org/data) as labelled ground truth to spot-check our policy analysis.

**Goes into:** `ingestion/compliance_loader.py` metadata taxonomy; evaluation data.
**Priority: MEDIUM.**

---

## [4] Harkous et al. 2018 — Polisis (USENIX Sec)

**What we learn:** Domain-specific embeddings (trained on 130k policies) beat general embeddings on privacy text; hierarchical **segment-level** classification (88.4%) — classify each policy segment, then route.

**Borrow:** Segment-level routing: pre-tag policy sections by topic so only relevant sections are injected per compliance dimension (your planned long-policy handling in `policy_reader.py`). Their result also justifies your legal-BERT embedding choice — cite it.

**Goes into:** `ingestion/policy_reader.py` (section routing for >50k-word policies).
**Priority: MEDIUM.**

---

## [5] Zimmeck et al. 2017 — Mobile-app privacy requirements (NDSS)

**What we learn:** First notice-vs-practice system: policy classifiers + static API analysis over 17,991 Android apps. Key design: a **small closed set of practices checkable in BOTH text and behaviour** (location, device ID, contacts × first/third party). Their static analysis produced false positives from dead code — the argument for our runtime evidence.

**Borrow:** The closed practice-set design — our HAR-evidence-type → dimension mapping is the web analogue; keep every dimension backed by an observable signal where possible.

**Goes into:** `rag/dimensions.py` — audit the 14 dimensions so each behavioral one has a defined HAR evidence type.
**Priority: MEDIUM.**

---

## [6] Ravichander et al. 2019 — PrivacyQA (EMNLP)

**What we learn:** 1,750 questions over app policies with legal-expert annotations; large human–model gap; many questions **unanswerable** from the policy — experts disagree.

**Borrow:** Abstention: when the policy doesn't address a dimension, output verdict `PARTIAL`/`NOT_ADDRESSED` with low confidence instead of forcing PASS/FAIL. Dataset (github: AbhilashaRavichander/PrivacyQA_EMNLP) as a retrieval sanity check.

**Goes into:** `rag/scorer.py` prompt schema (add `NOT_ADDRESSED` verdict + confidence field).
**Priority: HIGH — cheap change, big rigor gain.**

---

## [7] Zimmeck et al. 2019 — MAPS (PoPETs)

**What we learn:** Scaled notice-vs-practice to 1M+ apps: cheap classifiers first, expensive analysis second; results always phrased as **"potential non-compliance"** (legal prudence).

**Borrow:** (a) Cost tiering — Haiku for bulk dimension scoring, Sonnet only for report assembly (already your plan; cite MAPS as precedent). (b) "Potential violation" wording in all report output — a student project should not assert legal conclusions.

**Goes into:** `rag/report_builder.py` language; pipeline batching design.
**Priority: LOW (wording change now, scale later).**

---

## [8] Xiao et al. 2023 — Lalaine (USENIX Sec)

**What we learn:** Audited 5,102 iOS apps against Apple privacy labels via dynamic traffic capture; 3,423 non-compliant. Their non-compliance **typology**: *neglect* (behaviour not disclosed: 3,281), *contrary* (disclosure contradicts behaviour: 1,628), *inadequate* (disclosure too vague: 677). Consistency modeled as (data type, purpose, recipient) tuples.

**Borrow:** The neglect/contrary/inadequate typology as the classification for every policy-vs-HAR finding — makes reports far more precise than PASS/FAIL alone. The tuple model matches our `declared_vs_actual` comparison.

**Goes into:** `rag/scorer.py` output schema (`discrepancy_type` field), `rag/report_builder.py`.
**Priority: HIGH — direct upgrade to the core differentiator.**

---

## [9] Guha et al. 2023 — LegalBench (NeurIPS)

**What we learn:** 162 legal-reasoning tasks incl. OPP-115-derived privacy tasks; IRAC framing (Issue → Rule → Application → Conclusion) structures legal prompts well.

**Borrow:** (a) Run LegalBench privacy tasks (https://github.com/HazyResearch/legalbench) on candidate scorer LLMs before committing — one afternoon, gives an evaluation table for the paper. (b) IRAC prompt structure: Issue = dimension, Rule = retrieved article, Application = policy + HAR evidence, Conclusion = verdict.

**Goes into:** `rag/scorer.py` prompt template; model-selection experiment for the evaluation section.
**Priority: MEDIUM.**

---

## [10] Xie et al. 2025 — LLM policy evaluation at scale (USENIX Sec 25)

**What we learn:** Systematized **34 clauses from 10 privacy laws (4 themes)**; LLM pipeline scored 100k+ policies with F1 ≥ 0.84 (avg 0.94) validated against human-annotated subsets. Proves LLM-vs-codified-law scoring works at scale — on text only.

**Borrow:** (a) Cross-check our 14 dimensions against their 34 clauses — extend or justify omissions (paper: https://www.usenix.org/conference/usenixsecurity25/presentation/xie). (b) Their validation protocol: hand-annotate a small site sample, report per-dimension F1 — this should be our evaluation design.

**Goes into:** `rag/dimensions.py` (coverage check); evaluation plan (M5).
**Priority: HIGH for evaluation design.**

---

## Sprint order for next week

1. **Day 1–2:** `har_extractor.py` — profiling-cookie rule [1], cookie-purpose classification [2], evidence dict for prompts
2. **Day 2–3:** `telemetry_collector.py` — banner detection + accept/reject interaction (EasyList Cookie + element heuristics from alsacnc) [2]
3. **Day 3–4:** `rag/scorer.py` — IRAC prompt [9], `discrepancy_type` [8], `NOT_ADDRESSED` verdict + confidence [6], "potential violation" wording [7]
4. **Day 4–5:** `rag/dimensions.py` — reconcile with Xie's 34 clauses [10] + evidence-type audit [5]
5. **Day 5–6:** Wire scorer end-to-end on 2–3 sites; hand-label them for a mini F1 evaluation [10]
6. **Day 7:** Report builder + writeup

## Artifact links

| Paper | Artifact |
|---|---|
| [1] | CookieCheck tool + dataset (links in paper); HttpArchive: https://httparchive.org |
| [2] | https://github.com/bouhoula/alsacnc |
| [3] | https://usableprivacy.org/data (OPP-115_v1_0.zip) |
| [6] | https://github.com/AbhilashaRavichander/PrivacyQA_EMNLP |
| [9] | https://github.com/HazyResearch/legalbench |
| [10] | https://www.usenix.org/system/files/usenixsecurity25-xie.pdf |
