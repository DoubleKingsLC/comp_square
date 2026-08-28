# Evaluation Protocol

Addresses the three points raised at the Deliverable-2 supervision meeting:
test at scale, draw limitations from the data, and verify the model is not
hallucinating.

---

## 1. Running the batch

```bash
source venv/bin/activate
export OPENAI_API_KEY=...

# smoke test on 3 sites first (~5 min, few cents)
python3 evaluation/batch_audit.py --limit 3

# full run — 20 sites, 3 dimensions each
python3 evaluation/batch_audit.py

# deeper run once the 3-dimension pass looks right
python3 evaluation/batch_audit.py --preset behavioural --force
```

The harness checkpoints after every site, so it can be interrupted (Ctrl-C)
and resumed; sites with an existing report are skipped unless `--force`.
Edit `evaluation/sites.txt` to add or remove targets — sector and jurisdiction
labels drive the grouped tables.

**Outputs** (`evaluation/results/`)

| File | Contents |
|---|---|
| `batch_results.csv` | one row per site: status, capture health, verdict counts, score, grounding rate, runtime |
| `batch_results.json` | full detail including per-dimension verdicts |
| `summary.md` | markdown tables ready to paste into the paper |
| `verification/<domain>.json` | per-site grounding-verification detail |

Cost estimate: 3 dimensions × 20 sites ≈ 60 gpt-4o-mini calls, well under $1.
The `behavioural` preset (8 dimensions) is ~160 calls.

---

## 2. Verifying that findings are genuine (anti-hallucination)

`evaluation/verify_report.py` re-checks every verdict against the artefacts it
was produced from. No LLM is involved: it is pure string/structure checking, so
it cannot itself hallucinate.

| Check | Question it answers |
|---|---|
| **C1 citation grounding** | Was the cited article actually retrieved and placed in the prompt? (uses the `retrieved_articles` provenance now recorded by the scorer) |
| **C2 requirement quote** | Does the quoted legal text appear verbatim in the retrieved rule text? |
| **C3 policy quote** | Does the quoted policy claim appear in the scraped policy file? |
| **C4 behavioural claims** | Does every domain, cookie name and count named in the finding exist in the telemetry evidence dict? |
| **C5 consistency** | Internal rules: NOT_ADDRESSED must not carry a breach; a discrepancy type requires both a policy quote and behavioural evidence; score must sit in its verdict's band; FAIL/PARTIAL must rest on at least one piece of evidence |

Quote matching normalises whitespace, smart quotes and dashes, accepts elided
quotes (`...`) if every fragment matches, and accepts near-verbatim matches at
≥0.90 similarity. Anything looser is reported as a paraphrase, not a quotation.

Run standalone against any report:

```bash
python3 evaluation/verify_report.py compliance_reports/www.example.com_20260812_report.json \
    --evidence telemetry_output/www.example.com_evidence.json \
    --json evaluation/results/verification/www.example.com.json
```

**Interpreting the output.** The headline number is the *grounding rate*: the
fraction of dimensions in which every claim traces back to a source artefact.
Flagged claims are listed with the check that caught them. Note the important
distinction for the write-up: a flag is not automatically a hallucination —
C3 flags often mean the policy scraper captured a different page than the model
quoted, and C1 flags may mean retrieval served the wrong article (the model
obeyed its instructions). Each flag must be read to decide which component
failed. That triage is the substance of the limitations section.

**Manual spot-check (do this for 3–5 sites).** For each flagged claim, open the
HAR/telemetry JSON and the policy markdown and confirm by hand. Record the
outcome in the table below — a handful of manually confirmed cases is what
makes the automated numbers credible in the viva.

| Site | Dimension | Flag | Manual finding | Verdict on the flag |
|---|---|---|---|---|
| | | | | true hallucination / retrieval fault / scraper fault / false alarm |

---

## 3. Drawing the limitations from the data

After the batch, `summary.md` gives the raw material. Work through these
questions and write the answers into the paper's limitations subsection:

1. **Coverage.** What fraction of sites produced a degenerate capture? Which
   sectors? (Bot protection is expected to dominate; report the rate, name the
   sites, and state the mitigation as future work.)
2. **Policy retrieval.** How often did the scraper find zero policy files, and
   why — cross-domain hosting, JavaScript-rendered links, login walls? This
   bounds every policy-text dimension.
3. **Discrimination.** Do sector means separate the way the literature predicts
   (news worst, education/government best)? If they do not, is that a property
   of the sites or a defect in the scoring?
4. **Grounding.** What is the mean grounding rate, and what does the flag
   breakdown say about *where* errors concentrate (retrieval vs generation vs
   scraping)?
5. **Stability.** Re-run 2–3 sites with `--force` and compare verdicts. At
   temperature 0 they should be identical; any drift is worth reporting.
6. **Jurisdiction.** Do `.in` sites retrieve DPDP articles rather than GDPR
   ones? Check a DPDP verdict's `retrieved_articles` field.

---

## 4. What to report in the paper

- Table: per-site results (from `summary.md`).
- Table: sector aggregation with mean scores and FAIL rates, compared against
  the published sector ordering of Trevisan et al.
- Grounding verification: mean grounding rate, flag counts by check type, and
  the manual triage of a sample — this is the evidence that findings are
  genuine rather than model confabulation.
- Limitations subsection driven by items 1–6 above.
