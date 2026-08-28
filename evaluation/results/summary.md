# Batch audit summary

Generated 2026-08-16 20:07 UTC · 20 sites attempted · 15 scored · 2 blocked · 2 failed

## Per-site results

| Site | Sector | Juris. | Status | Score | Verdict | FAIL | PARTIAL | N/A | Policies | Grounding |
|---|---|---|---|---|---|---|---|---|---|---|
| www.independent.ie | news | IE | ok | 34 | POTENTIAL_NON_COMPLIANCE | 2 | 1 | 0 | 1 | 100% |
| www.irishtimes.com | news | IE | ok | 34 | POTENTIAL_NON_COMPLIANCE | 1 | 2 | 0 | 2 | 100% |
| www.rte.ie | news | IE | ok | 34 | POTENTIAL_NON_COMPLIANCE | 0 | 3 | 0 | 1 | 100% |
| www.thejournal.ie | news | IE | ok | 0 | POTENTIAL_NON_COMPLIANCE | 3 | 0 | 0 | 0 | 33% |
| www.bbc.co.uk | news | UK | ok | 0 | POTENTIAL_NON_COMPLIANCE | 2 | 0 | 1 | 0 | 50% |
| www.theguardian.com | news | UK | ok | 44 | POTENTIAL_NON_COMPLIANCE | 0 | 3 | 0 | 2 | 100% |
| www.universityofgalway.ie | education | IE | ok | 15 | POTENTIAL_NON_COMPLIANCE | 3 | 0 | 0 | 2 | 100% |
| www.tcd.ie | education | IE | ok | 34 | POTENTIAL_NON_COMPLIANCE | 1 | 2 | 0 | 1 | 67% |
| www.ucd.ie | education | IE | ok | 34 | POTENTIAL_NON_COMPLIANCE | 1 | 2 | 0 | 2 | 100% |
| www.citizensinformation.ie | government | IE | ok | 53 | PARTIAL | 0 | 2 | 0 | 2 | 100% |
| www.gov.ie | government | IE | ok | None | INSUFFICIENT_DATA | 0 | 0 | 3 | 0 | — |
| www.hse.ie | health | IE | collector_failed | — | — | — | — | — | — | — |
| www.overleaf.com | saas | UK | ok | 44 | POTENTIAL_NON_COMPLIANCE | 0 | 3 | 0 | 1 | 100% |
| www.dunnesstores.com | ecommerce | IE | collector_failed | — | — | — | — | — | — | — |
| www.harveynorman.ie | ecommerce | IE | ok | 0 | POTENTIAL_NON_COMPLIANCE | 2 | 0 | 1 | 0 | 50% |
| www.aerlingus.com | ecommerce | IE | ok | 6 | POTENTIAL_NON_COMPLIANCE | 2 | 1 | 0 | 2 | 100% |
| www.iitm.ac.in | education | IN | ok | 34 | POTENTIAL_NON_COMPLIANCE | 2 | 1 | 0 | 2 | 100% |
| www.irctc.co.in | ecommerce | IN | blocked | — | — | — | — | — | — | — |
| www.ndtv.com | news | IN | blocked | — | — | — | — | — | — | — |
| www.facebook.com | social | US | ok | 25 | POTENTIAL_NON_COMPLIANCE | 1 | 2 | 0 | 2 | 100% |

## By sector

| Sector | Sites scored | Mean score | FAIL verdicts / dimension |
|---|---|---|---|
| government | 1 | 53.0 | 0/3 (0%) |
| saas | 1 | 44.0 | 0/3 (0%) |
| education | 4 | 29.2 | 7/12 (58%) |
| social | 1 | 25.0 | 1/3 (33%) |
| news | 6 | 24.3 | 8/18 (44%) |
| ecommerce | 2 | 3.0 | 4/6 (67%) |

## Confound check: score vs policy availability

| Policy files retrieved | Sites | Mean score | Mean grounding |
|---|---|---|---|
| 0 | 3 | 0.0 | 44% |
| 1 | 4 | 36.5 | 92% |
| 2 | 8 | 30.6 | 100% |

Sites with no policy retrieved score **33 points lower** on average (0.0 vs 32.6). Scores for those sites reflect the auditing pipeline's retrieval coverage as much as the site's compliance, and must be reported separately.

## Per-dimension verdict distribution

| Dimension | FAIL | PARTIAL | PASS | NOT_ADDRESSED | distinct verdicts |
|---|---|---|---|---|---|
| disclosure_of_third_parties | 7 | 8 | 0 | 0 | 2 |
| pre_consent_tracking | 3 | 10 | 0 | 2 | 3 |
| tracking_without_consent | 10 | 4 | 1 | 0 | 3 |

A dimension with only one distinct verdict across all sites carries little discriminating information and should be examined.

## Score distribution

- range: **0–53** · mean **26.1** · distinct values: **7** of 15 sites

| Overall score | Sites |
|---|---|
| 0 | 3 |
| 6 | 1 |
| 15 | 1 |
| 25 | 1 |
| 34 | 6 |
| 44 | 2 |
| 53 | 1 |

Clustering on round values (0/25/50/75) indicates the model is anchoring on rubric points rather than using a continuous scale — report verdicts as ordinal, not scores as interval data.

## Grounding verification (hallucination check)

- Reports verified: **15**
- Mean grounding rate (dimensions with every claim traced to source): **86.7%**
- Total unsupported claims flagged: **5**

| Check | Flags | Example |
|---|---|---|
| C2 — requirement quote not verbatim | 1 | www.tcd.ie: C2: requirement_text not found in retrieved law text (no matching text found in source, best ratio 0.468) |
| C5 — internal inconsistency | 4 | www.thejournal.ie: C5: discrepancy_type 'neglect' asserted although no policy text was retrieved — non-disclosure cannot be estab |

**Attribution of flags**

| Cause | Flags | Interpretation |
|---|---|---|
| Fabricated behavioural claim | 0 | a domain, cookie or count that is not in the telemetry |
| Unlocatable quotation | 1 | quoted text not found in the source document |
| Paraphrase instead of quotation | 0 | substantively correct but not copied verbatim |
| Over-claim on a missing input | 4 | non-disclosure asserted about a policy that was never retrieved |
| Structural inconsistency | 0 | citation or schema rule violated |

## Sites that could not be captured

| Site | Requests | UI elements |
|---|---|---|
| www.irctc.co.in | 0 | 0 |
| www.ndtv.com | 1 | 0 |

Capture failure rate: **2/20 (10%)** — bot protection is the principal coverage limitation.
