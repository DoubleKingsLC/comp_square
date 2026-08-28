"""
RAG Compliance Scorer — Phase 3
LLM-Driven Privacy Compliance Framework
Author: Aaron Joseph Jean — 25233118

For each compliance dimension, assembles an IRAC-structured prompt
(law = Rule, policy + telemetry = Facts) and asks the LLM for a
structured judgement.

Design decisions from the literature:
  * IRAC prompt framing (Issue-Rule-Application-Conclusion) — LegalBench,
    Guha et al. (NeurIPS 2023).
  * NOT_ADDRESSED verdict + confidence field — PrivacyQA, Ravichander et
    al. (EMNLP 2019): even legal experts disagree; never force PASS/FAIL
    when the policy is silent.
  * discrepancy_type ∈ {neglect, contrary, inadequate} — Lalaine, Xiao et
    al. (USENIX Sec 2023) non-compliance typology.
  * All findings phrased as POTENTIAL violations — MAPS, Zimmeck et al.
    (PoPETs 2019) legal-prudence convention.
  * Grounding: the exact retrieved article text is injected into the
    prompt; the model must quote it, never cite from memory.

Usage:
    python3 rag/scorer.py --domain www.example.com \
        --har telemetry_output/www.example.com_X.har \
        --telemetry telemetry_output/www.example.com_X_telemetry.json \
        --policy policy_documents/www.example.com_privacy_policy.md \
        --policy policy_documents/www.example.com_cookie_policy.md \
        [--regulations GDPR PECR] [--dimensions pre_consent_tracking ...] \
        [--dry-run] [--model claude-haiku-4-5]

    --dry-run prints the assembled prompts without calling the API
    (no key needed) — use it to inspect exactly what the LLM will see.

Requires: ANTHROPIC_API_KEY env var (unless --dry-run).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag.dimensions import DIMENSIONS_BY_ID, SEVERITY_WEIGHTS, get_dimensions

DEFAULT_MODEL = os.environ.get("SCORER_MODEL", "claude-haiku-4-5")
MAX_POLICY_CHARS = 60_000   # per policy document injected into the prompt

VERDICTS = {"PASS", "FAIL", "PARTIAL", "NOT_ADDRESSED"}

SYSTEM_PROMPT = """\
You are a privacy-compliance analyst producing evidence for a research \
audit tool. You never assert definitive legal conclusions: every finding \
is a POTENTIAL violation pending review by a qualified lawyer.

You reason using the IRAC method:
  Issue      — the compliance question you are given.
  Rule       — ONLY the legal article text provided in the prompt. Never \
cite articles from memory; if the provided text does not cover the issue, \
say so.
  Application — apply the Rule to the two fact sources: (a) the site's \
written policy (the NOTICE) and (b) the observed runtime behaviour (the \
PRACTICE). Contradictions between notice and practice are the most \
important findings.
  Conclusion — a verdict and score.

Scoring scale:
  0-24   clear potential violation supported by behavioural evidence
  25-49  potential violation based on policy text or partial evidence
  50-74  partial compliance or ambiguous policy language
  75-100 compliant, clear policy language, no contradicting behaviour

Verdicts: PASS, FAIL, PARTIAL, or NOT_ADDRESSED (use NOT_ADDRESSED when \
the policy is silent on the issue AND there is no behavioural evidence \
either way — do not force PASS or FAIL).

discrepancy_type (only when notice and practice diverge, else null):
  "neglect"    — behaviour observed that the policy never discloses
  "contrary"   — policy claims one thing, behaviour shows the opposite
  "inadequate" — policy mentions the practice but too vaguely to satisfy \
the Rule

Quotation discipline: policy_claim and breach.requirement_text must be \
copied VERBATIM from the supplied text, character for character. Do not \
paraphrase, summarise, tidy up wording or merge sentences. If no single \
passage says what you need, set the field to null rather than composing one. \
Use "..." only to elide words inside an otherwise exact quotation.

Evidence discipline (strict):
  - Cite ONLY behaviour explicitly listed in the FACTS PART 2 block. Never \
infer, assume, or invent events that are not listed there.
  - If FACTS PART 2 states that no relevant events were observed, you MUST \
NOT report a behavioural violation — treat observed behaviour as compliant \
for this dimension and judge the policy text on its own merits.
  - The audit crawler intentionally performs no consent interaction; that \
statement describes our measurement protocol and is never itself evidence \
of a violation.

Respond with ONLY a valid JSON object matching the schema in the prompt. \
No markdown fences, no commentary."""

USER_PROMPT_TEMPLATE = """\
ISSUE (compliance dimension: {dim_id}):
{issue}
Indicative provisions: {law_refs}

RULE — retrieved legal article text (cite ONLY from this):
{law_context}

FACTS PART 1 — WEBSITE POLICY (the "notice"):
{policy_context}

FACTS PART 2 — OBSERVED RUNTIME BEHAVIOUR (the "practice"):
{evidence_context}

Apply the Rule to the Facts (IRAC) and return ONLY this JSON:
{{
  "dimension": "{dim_id}",
  "score": <integer 0-100>,
  "verdict": "PASS" | "FAIL" | "PARTIAL" | "NOT_ADDRESSED",
  "confidence": <float 0.0-1.0>,
  "breach": {{
    "regulation": "<string or null>",
    "article": "<string or null>",
    "requirement_text": "<short quote from the Rule text above, or null>"
  }},
  "policy_claim": "<short quote from the policy, or null if silent>",
  "policy_section": "<heading/section of that quote, or null>",
  "behavioral_evidence": "<the specific observed behaviour relied on, or null>",
  "discrepancy_type": "neglect" | "contrary" | "inadequate" | null,
  "explanation": "<2-3 plain-English sentences applying rule to facts>",
  "recommendation": "<the concrete change the site should make>"
}}"""


# ─────────────────────────────────────────────────────────────────────────────
# Context assembly
# ─────────────────────────────────────────────────────────────────────────────
def load_policies(policy_paths: list[str]) -> str:
    """Read scraped policy .md files (full text — see architecture doc §3.2)."""
    if not policy_paths:
        return ("No policy document was retrieved by the auditing crawler. "
                "IMPORTANT: this may be a retrieval failure (bot-blocking, "
                "cross-domain hosting) rather than the site lacking a policy — "
                "do NOT treat the absence of policy text as evidence that no "
                "policy exists or as a violation in itself. Treat the policy "
                "as unavailable; cap confidence at 0.6. Because the notice "
                "could not be read, you MUST set policy_claim to null and "
                "discrepancy_type to null: with no policy text it is impossible "
                "to establish that something was undisclosed, contradicted or "
                "inadequately described. Judge only the observed behaviour "
                "against the retrieved law.")
    blocks = []
    for p in policy_paths:
        path = Path(p)
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_POLICY_CHARS:
            text = text[:MAX_POLICY_CHARS] + "\n[... truncated ...]"
        blocks.append(f"--- {path.name} ---\n{text}")
    return "\n\n".join(blocks)


def select_evidence(evidence: dict | None, dim: dict, max_items: int = 12) -> tuple[str, bool]:
    """Render only the evidence keys relevant to this dimension.
    Returns (context_text, has_events) — has_events is True iff at least one
    of the dimension's evidence keys contains actual observed events."""
    if evidence is None:
        return ("No behavioural telemetry available for this scan. Judge on "
                "the policy text alone; prefer NOT_ADDRESSED or lower "
                "confidence where behaviour would be needed."), False

    lines = [
        f"Scan of {evidence.get('domain')}.",
        "AUDIT PROTOCOL NOTE: our crawler deliberately performed NO consent "
        "interaction (clean-profile first visit). This is a property of the "
        "audit, NOT a failing of the site — do not cite it as a violation.",
        f"Consent UI present on the page: {evidence.get('consent_ui_detected')}.",
        f"Tracker classification mode: {evidence.get('tracker_list_mode')}.",
    ]

    for key in dim["evidence_keys"]:
        val = evidence.get(key)
        if key == "consent_ui_detected" or val in (None, [], {}):
            continue
        if isinstance(val, list):
            lines.append(f"\n{key} ({len(val)}):")
            for item in val[:max_items]:
                if isinstance(item, dict):
                    if "name" in item:      # cookie record
                        life = item.get("lifetime_days")
                        life = f"{life:.0f}d" if isinstance(life, (int, float)) else "session"
                        lines.append(f"  - cookie '{item['name']}' ({item.get('cookie_domain')}), lifetime {life}")
                    else:                   # tracker request etc.
                        lines.append(f"  - {item.get('domain', item)} [{item.get('category', '')}]")
                else:
                    lines.append(f"  - {item}")
            if len(val) > max_items:
                lines.append(f"  ... and {len(val) - max_items} more")
        elif isinstance(val, dict):         # declared_vs_actual
            lines.append(f"\n{key}: {json.dumps(val, indent=1)[:2000]}")
        else:
            lines.append(f"\n{key}: {val}")

    has_events = len(lines) > 4
    if not has_events and dim["evidence_keys"]:
        lines.append(
            "\nNO events of the relevant evidence types were observed in this "
            "scan. IMPORTANT: absence of observed events means you MUST NOT "
            "assert a behavioural violation for this dimension. Judge the "
            "policy text alone; if behaviour was the deciding factor, this "
            "counts as evidence of compliance, not violation.")
    if not dim["evidence_keys"]:
        lines.append("\n(This dimension is assessed on policy text; behavioural "
                     "evidence is not applicable.)")
    return "\n".join(lines), has_events


def build_prompt(dim: dict, law_context: str, policy_context: str,
                 evidence_context: str) -> str:
    return USER_PROMPT_TEMPLATE.format(
        dim_id=dim["id"], issue=dim["issue"], law_refs=dim["law_refs"],
        law_context=law_context, policy_context=policy_context,
        evidence_context=evidence_context,
    )


# ─────────────────────────────────────────────────────────────────────────────
# LLM call + response validation
# ─────────────────────────────────────────────────────────────────────────────
def call_llm(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Provider is inferred from the model name:
         claude-*  -> Anthropic (ANTHROPIC_API_KEY)
         gpt-* / o* -> OpenAI   (OPENAI_API_KEY)
    """
    if model.startswith("claude"):
        import anthropic
        client = anthropic.Anthropic()   # uses ANTHROPIC_API_KEY
        msg = client.messages.create(
            model=model,
            max_tokens=1024,
            temperature=0,               # reproducible scoring runs
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    from openai import OpenAI
    client = OpenAI()                    # uses OPENAI_API_KEY
    resp = client.chat.completions.create(
        model=model,
        max_tokens=1024,
        temperature=0,                   # reproducible scoring runs
        response_format={"type": "json_object"},   # force valid JSON
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    return resp.choices[0].message.content


def parse_response(raw: str, dim_id: str) -> dict:
    """Parse + validate the model's JSON; degrade gracefully on bad output."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)   # strip fences
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return {"dimension": dim_id, "score": None, "verdict": "ERROR",
                "confidence": 0.0, "explanation": "Unparseable LLM response",
                "raw_response": raw[:2000]}

    obj["dimension"] = dim_id
    if obj.get("verdict") not in VERDICTS:
        obj["verdict"] = "PARTIAL"
    try:
        obj["score"] = max(0, min(100, int(obj.get("score"))))
    except (TypeError, ValueError):
        obj["score"] = None
    try:
        obj["confidence"] = max(0.0, min(1.0, float(obj.get("confidence"))))
    except (TypeError, ValueError):
        obj["confidence"] = 0.5
    if obj.get("discrepancy_type") not in ("neglect", "contrary", "inadequate", None):
        obj["discrepancy_type"] = None
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# Aggregation (severity-weighted, NOT_ADDRESSED excluded)
# ─────────────────────────────────────────────────────────────────────────────
def aggregate(results: list[dict]) -> dict:
    scored = [r for r in results
              if r.get("score") is not None and r["verdict"] not in ("NOT_ADDRESSED", "ERROR")]
    if not scored:
        return {"overall_score": None, "overall_verdict": "INSUFFICIENT_DATA"}
    total_w = weighted = 0.0
    for r in scored:
        w = SEVERITY_WEIGHTS[DIMENSIONS_BY_ID[r["dimension"]]["severity"]]
        total_w += w
        weighted += w * r["score"]
    overall = round(weighted / total_w)
    verdict = ("LIKELY_COMPLIANT" if overall >= 75 else
               "PARTIAL" if overall >= 50 else
               "POTENTIAL_NON_COMPLIANCE")
    return {"overall_score": overall, "overall_verdict": verdict,
            "dimensions_scored": len(scored),
            "dimensions_not_addressed": sum(1 for r in results if r["verdict"] == "NOT_ADDRESSED")}


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline
# ─────────────────────────────────────────────────────────────────────────────
def score_site(domain: str,
               har: str | None = None,
               telemetry: str | None = None,
               policies: list[str] | None = None,
               regulations: list[str] | None = None,
               dimension_ids: list[str] | None = None,
               model: str = DEFAULT_MODEL,
               dry_run: bool = False,
               top_k: int = 4) -> dict:

    # Behavioural evidence (Phase 2 utility)
    evidence = None
    if har:
        from ingestion.har_extractor import extract
        evidence = extract(har, telemetry=telemetry)

    policy_context = load_policies(policies or [])
    dims = get_dimensions(dimension_ids)

    # Lazy import — retriever loads legal-BERT (slow); skip entirely on dry runs
    # so prompts can be inspected without the vector DB.
    if dry_run:
        law_lookup = None
    else:
        from rag.retriever import render_law_context, retrieve_for_dimension
        law_lookup = (retrieve_for_dimension, render_law_context)

    results = []
    for dim in dims:
        evidence_context, has_events = select_evidence(evidence, dim)

        # Deterministic insufficiency guard: with no policy text AND no
        # observed events of this dimension's types, there is nothing to
        # judge — abstain before retrieval or LLM invocation. Prevents the
        # failure mode observed on bot-blocked scans (ndtv.com, 2026-07-20)
        # where an empty capture produced confident FAIL verdicts.
        if not dry_run and not (policies or []) and not has_events:
            results.append({
                "dimension": dim["id"], "score": None,
                "verdict": "NOT_ADDRESSED", "confidence": 0.3,
                "breach": None, "policy_claim": None, "policy_section": None,
                "behavioral_evidence": None, "discrepancy_type": None,
                "explanation": ("No policy document retrieved and no "
                                "behavioural events of the relevant types "
                                "observed — insufficient evidence to assess. "
                                "(Deterministic guard; LLM not invoked.)"),
                "recommendation": ("Re-run the scan; if the capture was "
                                   "degenerate the site may be blocking the "
                                   "headless browser."),
                "severity": dim["severity"],
            })
            print(f"[*] {dim['id']}: insufficient evidence — NOT_ADDRESSED (guard)")
            continue

        chunks = []
        if law_lookup:
            retrieve_for_dimension, render_law_context = law_lookup
            chunks = retrieve_for_dimension(dim["retrieval_query"],
                                            law_refs=dim["law_refs"],
                                            requirement_type=dim["requirement_type"],
                                            regulations=regulations, top_k=top_k)
            law_context = render_law_context(chunks)
        else:
            law_context = "[dry-run: legal articles would be retrieved here]"

        prompt = build_prompt(dim, law_context, policy_context, evidence_context)

        if dry_run:
            print(f"\n{'='*70}\nPROMPT for dimension: {dim['id']}\n{'='*70}")
            print(prompt[:4000])
            results.append({"dimension": dim["id"], "verdict": "DRY_RUN"})
            continue

        print(f"[*] Scoring {dim['id']} ...")
        raw = call_llm(prompt, model=model)
        result = parse_response(raw, dim["id"])
        result["severity"] = dim["severity"]
        # Retrieval provenance — makes the verdict auditable after the fact:
        # which articles were actually placed in front of the model, and the
        # exact rule text it was allowed to quote. Consumed by
        # evaluation/verify_report.py to detect ungrounded citations.
        result["retrieved_articles"] = [
            {"regulation": c.get("regulation"), "article": c.get("article"),
             "score": c.get("score")} for c in chunks]
        result["rule_text"] = law_context
        results.append(result)
        print(f"    -> {result['verdict']} (score {result.get('score')}, "
              f"confidence {result.get('confidence')})")

    report = {
        "domain": domain,
        "scan_date": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "regulations_filter": regulations,
        "har_file": har,
        "policies": policies,
        "disclaimer": ("Automated research output. All findings are POTENTIAL "
                       "violations and do not constitute legal advice."),
        **(aggregate(results) if not dry_run else {}),
        "dimensions": results,
    }
    return report


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Score a website's privacy compliance (RAG + LLM).")
    ap.add_argument("--domain", required=True)
    ap.add_argument("--har")
    ap.add_argument("--telemetry")
    ap.add_argument("--policy", action="append", default=[],
                    help="Policy .md file (repeatable)")
    ap.add_argument("--regulations", nargs="*", help="e.g. GDPR PECR")
    ap.add_argument("--dimensions", nargs="*", help="Subset of dimension ids")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print prompts; no API key or vector DB needed")
    ap.add_argument("--out", help="Output JSON path "
                    "(default compliance_reports/<domain>_<date>_report.json)")
    args = ap.parse_args()

    report = score_site(args.domain, har=args.har, telemetry=args.telemetry,
                        policies=args.policy, regulations=args.regulations,
                        dimension_ids=args.dimensions, model=args.model,
                        dry_run=args.dry_run)

    if not args.dry_run:
        out = args.out
        if not out:
            Path("compliance_reports").mkdir(exist_ok=True)
            date = datetime.now(timezone.utc).strftime("%Y%m%d")
            out = f"compliance_reports/{args.domain}_{date}_report.json"
        Path(out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\n[✓] Report written to {out}")
        print(f"    Overall: {report.get('overall_score')} ({report.get('overall_verdict')})")
