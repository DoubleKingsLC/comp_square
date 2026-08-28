# Viva Preparation Plan — 15 Days

30 minutes, supervisor + external examiner. The supervisor knows the project;
the external will not. Assume roughly: 10 minutes presentation, 20 minutes
questions, most of them from the external.

**What the external is actually testing.** Not whether the system is
impressive, but whether *you* built it, understand it, and know where it is
weak. The strongest signal you can give is volunteering a limitation before
being asked, and being able to explain any line of your own code.

---

## The three things you must be able to do without notes

1. **Explain the project in 60 seconds, then in 5 minutes.** Same content, two depths.
2. **Open any file in the repo and explain what it does and why it exists.**
3. **State the weaknesses of your own work before the examiner finds them.**

---

## Day-by-day plan

### Days 1–3 — Finish the work so preparation is not competing with building

- **Day 1:** re-run the full batch with the corrected prompts (`--force`). Update the paper's numbers if they shift (Section IV tables, and the 30-point confound figure). Re-run `verify_report.py` and confirm the flag count drops.
- **Day 2:** hand-annotate 5 sites × 3 dimensions against the article text. This is the missing ground truth and takes about two hours. Even a small F1 table converts "I did not evaluate accuracy" into "I evaluated accuracy on a small sample and report the limitation".
- **Day 3:** take the screenshots for the deck placeholders (slide 12: report → evidence → HAR for one finding; slide 9: terminal showing a refusal and a success). Freeze the paper and the deck. **No more building after Day 3.**

### Days 4–6 — Own the papers

- **Day 4:** re-read Trevisan and Bouhoula properly (they are the two the external is most likely to know). For each: method, headline number, limitation, what you took.
- **Day 5:** the other eight, at the level of `PREP_Deliverable2.md` Section A — pitch, method, numbers, limitation, what you took.
- **Day 6:** self-test. Cover the notes and speak for 60 seconds on each of the ten. Anything you stumble on goes on a one-page cheat sheet you re-read on the morning of the viva.

### Days 7–9 — Own the code

- **Day 7:** walk the pipeline in execution order with the repo open, narrating aloud: `telemetry_collector.py` → `har_extractor.py` → `compliance_loader.py` / `ingest.py` → `retriever.py` → `scorer.py` → `report_builder.py` → `verify_report.py` → `batch_audit.py`. One sentence of purpose, then the interesting detail, for each.
- **Day 8:** the five things most likely to be probed. Be able to explain each at whiteboard level:
  1. the profiling-cookie rule and why each of the three conditions is there
  2. dimension-anchored retrieval and the Art 19 / Art 13(1)(e) incident that caused it
  3. the IRAC prompt and the evidence-discipline guards
  4. the severity-weighted aggregation and why NOT_ADDRESSED is excluded
  5. the five verification checks and why the checker uses no LLM
- **Day 9:** deliberately break things and know the answers. What happens if the vector DB is empty? If the policy is 200 pages? If the model returns malformed JSON? If two runs disagree? (Answers: fallback retrieval; truncation at 60k chars per document; `parse_response` clamps and degrades to an ERROR verdict; temperature 0 makes this unlikely and repeat-run variance is reported.)

### Days 10–12 — Rehearse

- **Day 10:** full run-through with slides, timed. Target 10 minutes for the presentation. Cut anything that does not survive the clock.
- **Day 11:** **mock viva with someone else** — ideally a classmate who will ask hostile questions; failing that, record yourself answering the question bank below in random order. Watch it back for filler and hedging.
- **Day 12:** second timed run-through. Prepare the demo: pre-generated reports open in browser tabs, terminal ready with the reuse-mode command, and a fallback if the network fails.

### Days 13–15 — Consolidate

- **Day 13:** one page of numbers you must not fumble (below). Re-read the paper end to end as an examiner would, marking anything you could not defend.
- **Day 14:** light. Re-read PROGRESS.md to refresh the chronology, and the limitations section. Do not learn anything new.
- **Day 15:** morning of — read the cheat sheet once. Check the laptop, the demo, the adapter, the PDF of the paper, and a printed copy of the deck.

---

## Numbers you must not fumble

| Fact | Value |
|---|---|
| Regulations ingested | GDPR (99 article chunks), PECR, DPDP |
| Compliance dimensions | 15 (8 behavioural, 7 policy-only) |
| Profiling-cookie rule | third-party ∧ in both tracker lists ∧ lifetime ≥ 30 days |
| Sites tested | 20 attempted, 15 scored, 2 blocked, 2 timed out, 1 insufficient data |
| Capture failure rate | 10% |
| Verification flags | 16 across 15 reports; **0 fabricated behavioural claims** |
| Policy-availability confound | 4.7 mean score with no policy vs 34.2 with policy |
| Trevisan baseline | 35,862 sites, 49% pre-consent violations, 86% news |
| Bouhoula baseline | 97k sites, 65.4% still collect after explicit rejection |
| Xie baseline | 34 clauses, 10 laws, avg F1 0.94 on policy text alone |

---

## Question bank

### Certain to be asked

1. **What is the contribution?** No prior system feeds live web telemetry, the scraped policy and retrieved law to an LLM together. Prior work masters one modality each; hybrid notice-vs-practice work exists only for mobile binaries via static analysis.
2. **How do you know the model is not hallucinating?** The verification tool re-checks every claim mechanically against the artefacts, with no LLM involved. Across 15 reports it found zero fabricated behavioural claims. The errors it did find were paraphrase and reasoning about unretrieved policies.
3. **Why an LLM at all — why not rules?** Rules handle the behavioural side well and are used for exactly that (the cookie rule is deterministic). The LLM is needed for the notice side: deciding whether a specific policy sentence adequately discloses an observed practice is a language-comprehension task no regex solves.
4. **What is the weakest part?** Policy retrieval. It accounts for about 30 points of score difference and is a limitation of my pipeline, not of the sites. Followed by: no independent ground truth yet, and coarse score granularity.
5. **Which parts are yours?** Point at CODE_PROVENANCE.md: all pipeline code is mine; adopted rules and typologies are cited at their point of use; tracker lists and libraries are third-party.

### Likely from an external

6. **Why not use OpenWPM / CookieCheck / the Bouhoula crawler?** They answer "how many sites violate" with aggregate statistics; this project answers "what is this site doing wrong, under which article, contradicted by which sentence", which needs structured per-site evidence their pipelines discard. Their validated *rules* are reused and cited.
7. **Is 20 sites enough?** No, and I say so. It is enough to expose pipeline limitations, not to make claims about sector compliance rates. Several sectors have one site.
8. **Your scores cluster on round numbers — is the score meaningful?** As an ordinal ranking, yes; as an interval measurement, no. That is stated in the paper and is why verdicts and evidence are the primary output.
9. **What if the law changes?** Swap the vector store; no retraining. That is a deliberate advantage of RAG over fine-tuning.
10. **Could this be used to make legal decisions?** No. Every output is phrased as *potential* non-compliance, following the MAPS convention. It produces evidence for a human reviewer.
11. **What about GDPR compliance of your own tool?** It visits public pages as a browser would, collects no personal data, and stores only technical telemetry. Worth saying you considered it.
12. **Why gpt-4o-mini?** Cost and strict JSON mode for bulk scoring; the architecture is provider-agnostic and Claude models are drop-in. Formal selection is future work via LegalBench.
13. **How would you scale this to 100k sites?** Parallel collection (the alsacnc model), cheap-model-first tiering (MAPS), and caching the legal retrieval per dimension since it does not change per site.

### Awkward ones — answer honestly, do not bluff

14. **Did you validate against a lawyer?** No. That is the principal remaining evaluation and is stated as a threat to validity.
15. **Your grounding rate was 62% — is that good?** It is not the right question in isolation. After triage: no fabricated evidence, 7 flags from a missing input, 5 paraphrases, 3 false positives in my own checker. The raw rate understates the model and overstates the problem, which is why the paper reports the attribution rather than the headline.
16. **You used AI to write code and text — how much is yours?** The declaration in the paper covers it. Design decisions, paper selection, experiments and analysis are mine; AI assisted with drafting and implementation. Then demonstrate ownership by explaining any part they point at. *This is why Days 7–9 matter.*

---

## Presentation structure for the 10 minutes

| Minutes | Content | Slides |
|---|---|---|
| 0–1 | The problem: notice vs practice, why manual auditing does not scale | 1, 3 |
| 1–2 | The gap in one sentence, and the contribution | 3 |
| 2–4 | Architecture and how a verdict is produced | 6, 7 |
| 4–6 | Evaluation method and coverage results | 8, 9 |
| 6–8 | Findings, and verification against telemetry (the worked example) | 10, 11, 12 |
| 8–9 | Limitations found by testing | 13 |
| 9–10 | Future work and close | 15, 16 |

Keep slides 4, 5, 14 as backup for questions rather than presenting them.

---

## On the day

- Have open: the HTML report, the evidence JSON, a verification JSON, and the repo.
- If you do not know something: "I did not test that — my expectation is X, and the way to check it would be Y." Examiners accept this; they do not accept invention.
- When you are asked about a weakness, agree first, then explain what you did about it or why you did not.
