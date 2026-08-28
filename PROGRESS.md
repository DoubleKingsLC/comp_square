# comp_square — Progress Log

Chronological record of implementation work. Newest first.

---

## 2026-08-27 — Viva presentation revised (16 slides)

Rebuilt to read as hand-made rather than generated, and slightly expanded. Layout is now deliberately uneven: a quote block, a single large statistic, side-by-side comparison panels, dense tables and sparse statement slides. Titles vary in form (statements, a question, plain nouns) instead of a uniform "Noun — subtitle" pattern, and the writing is first-person where a decision was mine.

New content: an opening slide built on the real independent.ie finding (verbatim Mediahuis policy quote against the domains actually contacted); per-paper "what I took" lines that justify each borrowed rule rather than list it; and a new slide separating **grounded** from **correct**, using cloudflare.com and jsdelivr.net from my own results as an example of a verdict that would pass all five checks and still be legally questionable. Speaker notes re-timed to ~12 minutes, leaving 18 for questions.

## 2026-08-26 — "No policy document" on independent.ie: two causes, both fixed

A frontend run reported no policy documents for independent.ie even though telemetry had captured the correct URLs and an applicable policy file was already on disk. Two independent faults:

1. **The scraper discarded working candidates.** Link classification picks the single highest-scoring URL per category. It chose the same-domain `independent.ie/privacy/policy` (score 39) over the telemetry-supplied `mediahuis.ie/privacystatement/`; the chosen URL returned **HTTP 403** and the category was lost outright. Fixed: runners-up are retained as `alternatives` and tried in score order until one yields a document, with the fallback logged. A single 403 no longer costs a category.
2. **Duplicated lookup logic had drifted.** `find_policies()` existed separately in `frontend/app.py` and `evaluation/batch_audit.py`; only the latter had learned about `evaluation/policy_map.json`, so the frontend could not see `www.mediahuis.ie_cookie_policy.md` sitting in `policy_documents/`. Fixed by extracting **`ingestion/policy_lookup.py`** as the single source of truth (exact domain → policy_map override → filename stem), with both callers delegating to it. Verified: independent.ie now resolves to the Mediahuis policy.

Worth noting for the viva: this is the policy-retrieval limitation reported in the paper appearing again in a new form, and it reinforces the finding that retrieval coverage — not site behaviour — is the dominant source of score distortion.

## 2026-08-17 (later 2) — Viva presentation

- **New `Viva_Presentation.pptx`** — 14 slides following the paper's own progression, timed in the speaker notes for ~14 minutes of a 30-minute viva. Literature is presented as four waves (policy text → mobile notice-vs-practice → dynamic web → LLM legal reasoning), each as a table of contribution and limitation with an "Adopted into comp_square" strip beneath. Then gaps→design mapping, architecture, module map, evaluation method, results, verification, limitations, future work. Every slide carries timed speaker notes.

## 2026-08-17 (later) — Viva audio-prep source

- **New `VIVA_AUDIO_SOURCE.md`** — ~5,600 words written specifically to be converted to audio (NotebookLM): no tables, no code blocks, no file paths, numbers spelled out in context, every explanation self-contained. Eight parts: the problem; the ten papers grouped by research direction; the system followed in data-flow order; design decisions with their defences; evaluation results; verification and the four failure modes (plus the two defects found in the verification tool itself); limitations; and a rapid-fire question bank. Includes suggested per-episode steering prompts so several short episodes can be generated rather than one long one.
- Added `Acknowledgment` section to the paper (required by the submission guidelines and previously missing). Recompiled: 9 pages, 35 references, 0 undefined citations.

## 2026-08-17 — Paper submitted

Final consistency pass before submission: run date corrected to 16 August, score-distribution wording corrected to seven distinct values, abstract and paper-organisation paragraph rewritten to match the restructured Sections IV–VI, and an explicit statement added that the reported batch predates the jurisdiction correction (Irish ePrivacy citations in that run name the UK instrument; GDPR findings unaffected; re-scoring under S.I. 336/2011 listed as immediate remaining work). Compiles clean: 9 pages, 35 references, 0 undefined citations. Submitted as `Jean_25233118_ComplianceAuditing_Final.pdf`.

**Carried forward for post-submission work:** re-score the Irish sample under S.I. 336/2011; re-read UK verdicts against DUAA 2025 Schedule A1; Day 2 blinded annotation and F1 study; screenshots for the deck placeholders.

---

## 2026-08-12 — Evaluation harness (supervisor feedback from Deliverable 2)

Supervisor asked for: (1) testing across many sites, (2) limitations drawn from that data, (3) verification that findings are genuine rather than hallucinated.

- `rag/scorer.py`: every verdict now records **retrieval provenance** — `retrieved_articles` (which articles were actually placed in the prompt) and `rule_text` (the exact text the model was allowed to quote). Without this, citations cannot be audited after the fact.
- **New `evaluation/verify_report.py`** — mechanical grounding check, no LLM involved, so it cannot itself hallucinate. Five checks per verdict: C1 cited article was actually retrieved · C2 requirement quote verbatim in the retrieved rule text · C3 policy quote verbatim in the scraped policy · C4 every domain/cookie/count named in the finding exists in the telemetry evidence dict · C5 internal consistency (NOT_ADDRESSED without breach, discrepancy type needs both sides, score within verdict band). Quote matching normalises whitespace/smart quotes, accepts elided quotes and ≥0.90 near-verbatim. Tested against fixtures with planted hallucinations (fabricated domain, invented cookie, ungrounded Art 19 citation, fabricated policy quote, inconsistent NOT_ADDRESSED): **all planted faults caught, genuine verdict passed**.
- **New `evaluation/batch_audit.py`** — runs the pipeline over a site list, resumable/checkpointed, records capture health (bot-blocking detection), policy retrieval success, per-dimension verdicts, timings, and runs the verifier per site. Emits `batch_results.csv`, `batch_results.json`, `summary.md` (per-site table, sector aggregation, grounding/hallucination table, capture-failure table).
- **New `evaluation/sites.txt`** — 20 sites labelled by sector and jurisdiction (news / education / government / health / saas / ecommerce / social; IE, UK, IN, US), including deliberate bot-protected cases; `.in` sites automatically add DPDP.
- **New `evaluation/PROTOCOL.md`** — how to run the batch, how to interpret grounding flags (a flag is not automatically a hallucination: it may be a retrieval or scraper fault — the triage is the substance of the limitations section), the manual spot-check table, and the six questions whose answers become the paper's limitations subsection.

## 2026-08-16 (later) — Jurisdiction error: PECR does not apply in Ireland

**Problem found:** the batch scored all sites against GDPR + PECR. PECR 2003 is UK law. Ireland transposed the ePrivacy Directive through **S.I. 336/2011**, whose cookie-consent provision is **Regulation 5(3)**, enforced by the Data Protection Commission. Eleven of the twenty sites are Irish, so every ePrivacy citation for those sites named the wrong instrument. GDPR citations are unaffected (GDPR applies EU-wide).

**Fix:** jurisdiction now selects the applicable instruments rather than a fixed default —
`IE → GDPR + EPRIVACY-IE`, `UK → GDPR + PECR`, `IN → DPDP`, `US → CCPA`; `--regulations` still overrides. `rag/dimensions.py` law references extended with `EPRIVACY-IE Reg 5`; `rag/retriever.py` reference parser updated (the hyphenated token must precede `ePrivacy` in the alternation). `evaluation/sites.txt` documents the mapping.

**Resolved:** S.I. 336/2011 downloaded from irishstatutebook.ie and ingested as `EPRIVACY-IE` (28 chunks). Reg 5(3), the operative cookie-consent provision, verified present in the store with the correct text. Note that `ingestion/test_query.py` runs an *unfiltered* search across all instruments, so a generic cookie query still returns PECR text; the scorer filters by regulation and anchors on `EPRIVACY-IE Reg 5`, so this is a property of the test tool, not the pipeline.

**Incidental finding worth reporting:** the ingested PECR text is the consolidated version and therefore includes the substitution of Reg 6 and the insertion of Schedule A1 by the **Data (Use and Access) Act 2025**, commenced 5 Feb 2026, which moves statistical/analytics cookies from opt-in to opt-out under defined conditions (sole statistical purpose, no wider sharing, clear information, free and simple objection). Two consequences: (a) UK verdicts (bbc, theguardian, overleaf) that penalised analytics trackers need re-reading against Schedule A1; (b) it is a concrete argument for the RAG design — the system applies amended law with no model change, whereas a fine-tuned model would still apply the pre-February rule. Both added to the paper's limitations subsection.

## 2026-08-16 — Second full batch + two verifier defects found and fixed

**Re-run after the prompt fixes:** grounding 62.2% → **86.7%**, flags 16 → **5**, fabricated behavioural claims **0**. Paraphrase flags 5 → 0 (quotation-discipline rule worked). gov.ie now correctly returns INSUFFICIENT_DATA.

**Two defects in the verification tool itself**, both inflating the apparent model error rate:
1. *Elided-quote matching was broken.* Ellipsis markers were stripped **before** the fragment split, so a valid quotation spanning a gap could never match. Confirmed against theguardian.com: both fragments were verbatim in the policy yet the quote was flagged. Fixed by checking fragments first.
2. *The `neglect` consistency rule was a category error.* "Neglect" means the policy never discloses the practice, so by definition there is no passage to quote; demanding a policy quotation was wrong. Rule corrected: `contrary`/`inadequate` require a quotation, `neglect` requires behavioural evidence **and** that a policy was actually retrieved.

After the fixes the 5 remaining flags are: 4 × over-claiming `neglect` on sites with no policy retrieved (genuine, now also blocked in the prompt), and 1 × tcd.ie quoting the Art 4(11) definition of consent when only Art 7 was retrieved (legally accurate, not a quotation of the supplied rule).

- Added `batch_audit.py --reverify`: re-runs grounding verification over existing reports offline with no API calls, so verifier changes can be re-measured for free.
- Flag attribution table rewritten with precise categories (fabricated behavioural claim / unlocatable quotation / paraphrase / over-claim on missing input / structural inconsistency).
- **Paper updated** with the final figures: sector means (gov 53.0, saas 44.0, education 29.2, social 25.0, news 24.3, ecommerce 3.0), score range 0–53 with seven distinct values, per-dimension distribution, grounding 86.7%, five-row attribution table, confound now 33 points (0.0 vs 32.6). Added a paragraph disclosing the two verifier defects, since validating the measuring instrument is part of the method. Compiles clean, 9 pages.

## 2026-08-13 (later) — Ground-truth annotation harness

- **New `evaluation/annotate.py`** — closes the "no independent ground truth" gap. `--prepare` builds a **blinded** annotation sheet: for each (site, dimension) it shows the retrieved legal requirement, a factual summary of the observed behaviour, and a keyword-selected policy excerpt, but deliberately not the system's verdict (an annotator who sees the model's answer tends to agree with it, inflating the result). `--score` compares the completed labels with the system verdicts and reports exact agreement, Cohen's kappa, per-class precision/recall/F1, macro-F1, a binary "concern raised" view, per-dimension agreement, and a confusion matrix, written to `evaluation/results/ground_truth.md` as paper-ready markdown.
- Policy-excerpt selection scores candidate windows for prose density so the annotator sees substantive text rather than a table of contents.
- Verified on the real batch: 9 rows across 3 sites generated correctly; scoring maths (P/R/F1, kappa) unit-tested.

## 2026-08-13 — Final-review materials

- **Paper:** Section IV rewritten from "Preliminary Results" to a full **Evaluation** section in the paper's existing register: method (three stages), Table V coverage outcomes, Table VI sector means, Section IV-C verification against telemetry with Table VII flag attribution, and IV-D limitations revealed by testing. Section V rewritten as **Threats to Validity and Remaining Evaluation** (no independent ground truth, sample size, single model). Conclusion updated with the batch and verification results. Compiles clean: 9 pages, 0 undefined citations.
- **Deck:** `FinalReview_Viva.pptx`, 16 slides. New: evaluation method, coverage results, sector findings, verification-with-flag-attribution, worked-example slide with **three screenshot placeholders** (report → evidence dict → raw HAR), limitations from testing; error-analysis table extended with the fourth failure mode; future work reordered to lead with the F1 study.
- **`VIVA_PLAN.md`:** 15-day schedule (finish work by day 3, papers days 4–6, code days 7–9, rehearsal 10–12, consolidation 13–15), the numbers not to fumble, a 16-question bank including the awkward ones, and a minute-by-minute structure for the 10-minute presentation.

## 2026-08-12 (later 4) — Full 20-site batch + triage of every flag

**Run:** 20 sites, 15 scored, 2 blocked (irctc.co.in, ndtv.com — 10% capture failure), 2 collector timeouts (hse.ie, dunnesstores.com), 1 INSUFFICIENT_DATA (gov.ie). Mean grounding 62.2%, 16 flags.

**Triage of all 16 flags — no fabricated behavioural evidence found:**
- 3 × C4 were **verifier false positives**: fingerprinting API names (`navigator.getBattery`, `HTMLCanvasElement.toDataURL`) matched the domain regex. Fixed with a JS-API exclusion list.
- 7 × C5 were **real over-claiming caused by a missing input**: on sites where no policy was retrieved, the model still asserted `discrepancy_type: neglect` — i.e. inferred non-disclosure from a document it had never seen. Fixed in the prompt: with no policy text, `policy_claim` and `discrepancy_type` must be null.
- 5 × C3 were **paraphrases** (similarity 0.85–0.90) rather than verbatim quotes. Fixed by adding an explicit quotation-discipline rule to the system prompt.
- 1 × C2 (tcd.ie, ratio 0.5) remains for manual inspection.

**Key finding — policy availability confounds the score.** Sites with 0 policy files retrieved average **4.7** and 0% grounding; sites with 1–2 policies average **34.2** and ~77%. A 30-point gap driven by our own retrieval coverage, not by site behaviour. Added a confound-check table to the summary; scores for zero-policy sites must be reported separately.

**Sector ordering:** government 44.0 · saas 44.0 · education 31.8 · news 26.7 · social 25.0 · ecommerce 12.5 — consistent with Trevisan et al. (government best) but ecommerce/news ordering is confounded by the policy-retrieval issue above.

**Other fixes:** `policy_scraper_2.py` crashed on thejournal.ie (`form.action.trim is not a function` — a form input named "action" shadows the property); hardened 5 DOM property reads with `String()`. Collector timeout raised 300s → 480s for slow sites. Summary now includes the confound table, per-dimension verdict distribution, score distribution, and flag attribution (fabrication vs paraphrase vs missing input).

## 2026-08-12 (later 3) — First clean batch: pipeline verified end-to-end

3/3 sites scored, 0 failed, 0 blocked (irishtimes.com, rte.ie fresh; independent.ie reused).
- **Grounding result (headline):** 100% on both fresh reports, 0 unsupported claims. Confirmed genuine rather than abstention — per-check tallies show C1 citation, C2 requirement quote and C3 policy quote all SUPPORTED 3/3, not N/A. Every cited article was actually retrieved, and every quoted legal/policy phrase appears verbatim in its source.
- **Observation — score clustering:** both fresh sites scored exactly 34 (50/25/25 per dimension). Evidence is genuinely site-specific (permutive.app vs aticdn.net), so this is not a default answer, but the model anchors on rubric values rather than a continuous scale. Implication for the paper: treat verdicts as ordinal, not scores as interval data.
- **Observation — low-information dimension:** `pre_consent_tracking` returns PARTIAL 50 whenever no profiling cookies are observed, across all three sites. Near-constant; needs either a sharper rubric or reporting alongside the raw cookie count.
- **Observation — possible over-leniency:** no FAIL verdicts on the fresh runs, whereas the pre-guard independent.ie report had 4. The evidence-discipline guards may have made the scorer conservative; calibration against hand labels will settle it.
- `batch_audit.py`: summary now includes per-dimension verdict distribution (flags dimensions with a single distinct verdict) and overall score distribution (exposes rubric clustering).

## 2026-08-12 (later 2) — Batch harness made environment-proof

Second batch run diagnosed instantly thanks to the new logging: `ModuleNotFoundError: No module named 'llama_index'` — the harness had been launched with the system Python, so every subprocess inherited it.
- `batch_audit.py` now resolves the project venv interpreter itself (`venv/bin/python3`) regardless of how it was launched.
- Added a **preflight check**: verifies the pipeline packages are importable in the chosen interpreter, the relevant API key is exported, and the vector store is non-empty — exits with a clear message before spending time or API credit.
- Added `requirements.txt` (was missing).

## 2026-08-12 (later) — Fixes from the first 3-site batch run

First real batch surfaced four issues, all fixed:
- **Silent failures:** 2/3 sites returned `scorer_failed` with no visible cause. `run()` now writes full stdout/stderr per site to `evaluation/results/logs/<domain>.log` and prints the last 12 lines inline on failure.
- **Verifier false positive:** the scanned site's own domain was flagged as "not in telemetry" (findings legitimately name the first party). The evidence universe now includes the scanned domain and its www-stripped form.
- **Legacy reports polluting the metric:** reports produced before retrieval provenance existed were scored as *ungrounded* (C1 "no provenance", C2 "source unavailable"). Those checks are now N/A, dimensions are marked `verifiable: false`, and the headline grounding rate is computed over verifiable dimensions only, with a "re-score with --force" notice.
- **Missing-policy handling:** when the verifier has no policy text, C3 is N/A and reported as a *verification gap*, not a model error. Added `evaluation/policy_map.json` so cross-domain policy hosting (independent.ie → mediahuis.ie) resolves correctly during batch runs.

## 2026-07-20 (later) — Deck rebuilt (v2)

- `Deliverable2_Supervisor_Update.pptx` regenerated: 14 slides, plain academic design (white, UoG maroon accent, Calibri). New/updated content: project status timeline; per-paper idea/code-taken tables with target modules; architecture with frontend; technical-choices incl. embedder finding; provenance; two-audit results (independent.ie + ndtv robustness case); three-failure error analysis; **paper-progress slide**; **six-step scoring-mechanism slide**; **future-work table**. Speaker notes updated throughout.

## 2026-07-20 (later) — Paper restructured to full-paper format

- `literature_review_ieee.tex` restructured to match the reference format (Intro A–D / integrated review / design+implementation with Algorithm 1 / results / conclusion): title subtitle dropped; abstract extended with prototype + preliminary results; new subsections Implementation Status & Practical Tools, Scoring Strategy, **Algorithm 1** (per-dimension RAG scoring incl. both deterministic guards); new **Section IV Preliminary Results and Error Analysis** (independent.ie audit + Table IV + three failure modes with fixes); new **Section V Evaluation Plan**; new **Section VI Conclusion and Future Work**. Gantt/milestones and Datasets sections removed (content folded into Implementation/Evaluation); Challenges folded into the evaluation-plan limitations. Compiles cleanly: 7 pages, 0 errors, 0 undefined citations. Output: `literature_review_ieee_updated.pdf`.

## 2026-07-20 — Robustness fixes from the ndtv.com hostile test

- **Failure observed:** ndtv.com bot-blocked the headless browser → degenerate capture (1 request, 0 UI elements, 0 policy links) → scorer produced FAIL 0 @ confidence 1.0 on three dimensions with zero evidence, treating "policy not retrieved" as "policy doesn't exist".
- `frontend/app.py`: **degenerate-capture gate** — scans with <10 requests or 0 UI elements are refused before scoring with a clear bot-blocking message; `.in` domains automatically add **DPDP** to the regulation set; DPDP options added to the UI.
- `rag/scorer.py`: **deterministic insufficiency guard** — no policy retrieved AND no behavioural events for a dimension ⇒ NOT_ADDRESSED (confidence 0.3) *without invoking retrieval or the LLM*; overall verdict becomes INSUFFICIENT_DATA. Missing-policy prompt rewritten: absence of scraped policy must not be treated as proof the site lacks one.
- All paths verified offline (guard skips LLM entirely; gate rejects the ndtv-shaped telemetry, passes independent.ie-shaped). Third documented error-analysis case for the paper: garbage-in detection.

## 2026-07-19 — Web frontend (`frontend/app.py`)

- Single-file Flask app wrapping the CLI pipeline: URL in → telemetry → evidence extraction → policies → RAG scoring → HTML report, with a live stage log (the exact subprocess commands are shown — the UI runs nothing the CLI doesn't). Dimension presets (demo 3 / behavioural 8 / full 15), regulation + model selectors, and a **reuse-existing-artifacts** mode for fast, reliable demos on pre-scanned sites. Smoke-tested end-to-end with stubbed pipeline CLIs (fresh + reuse paths, status polling, report serving). Run: `pip install flask && python3 frontend/app.py` → http://127.0.0.1:5001.

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
