"""
Report grounding verifier — Phase 6 (evaluation)
LLM-Driven Privacy Compliance Framework
Author: Aaron Joseph Jean — 25233118

Checks, mechanically and without an LLM, whether a scored report is actually
supported by its inputs. This is the faithfulness / hallucination check: every
claim the model made is traced back to the artefact it must have come from.

Five checks per dimension verdict:
  C1 CITATION GROUNDING  — the cited article was actually retrieved for that
                           dimension (uses `retrieved_articles` provenance).
  C2 REQUIREMENT QUOTE   — `breach.requirement_text` appears verbatim (modulo
                           whitespace/quote normalisation) in the rule text
                           that was placed in the prompt.
  C3 POLICY QUOTE        — `policy_claim` appears in the scraped policy files.
  C4 BEHAVIOURAL CLAIMS  — every domain / cookie name / count mentioned in
                           `behavioral_evidence` exists in the evidence dict
                           produced by har_extractor.
  C5 CONSISTENCY         — internal rules: NOT_ADDRESSED must not carry a
                           breach; a discrepancy_type requires both a policy
                           claim and behavioural evidence; score must match
                           the verdict band.

Each check yields SUPPORTED / UNSUPPORTED / NOT_APPLICABLE. UNSUPPORTED
findings are potential hallucinations and are listed individually.

Usage:
    python3 evaluation/verify_report.py compliance_reports/<domain>_<date>_report.json \
        --evidence telemetry_output/<domain>_evidence.json \
        [--policy policy_documents/x.md ...] [--json out.json] [--strict]

`--strict` exits 1 if any UNSUPPORTED claim is found (useful in CI / batch runs).
Policy files are auto-discovered from the report's `policies` field when present.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent

SUPPORTED, UNSUPPORTED, NA = "SUPPORTED", "UNSUPPORTED", "N/A"

# Quote matching thresholds. Models often paraphrase slightly or elide with
# "..."; we accept a high-similarity window match but flag anything looser.
FUZZY_ACCEPT = 0.90
FUZZY_PARTIAL = 0.75

VERDICT_BANDS = {  # verdict -> (min_score, max_score) sanity range
    "PASS": (60, 100),
    "PARTIAL": (25, 85),
    "FAIL": (0, 60),
}


# ─────────────────────────────────────────────────────────────────────────────
# Text normalisation and quote matching
# ─────────────────────────────────────────────────────────────────────────────
def norm(text: str) -> str:
    """Lowercase, unify quotes/dashes, collapse whitespace."""
    if not text:
        return ""
    t = str(text)
    for a, b in [("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
                 ("–", "-"), ("—", "-"), (" ", " ")]:
        t = t.replace(a, b)
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def quote_supported(quote: str, source: str) -> tuple[str, float, str]:
    """Is `quote` present in `source`? Returns (status, ratio, note)."""
    q, s = norm(quote), norm(source)
    if not q:
        return NA, 1.0, "no quote given"
    if not s:
        return UNSUPPORTED, 0.0, "source text unavailable"
    q = q.strip('"\'').strip()
    if len(q) < 12:
        return NA, 1.0, "quote too short to verify"

    # Elided quotes FIRST: the fragments must be checked before the ellipsis
    # markers are removed, otherwise the split finds nothing and a perfectly
    # valid elided quotation is reported as unmatched.
    frags = [f.strip(' .') for f in re.split(r"\.{3}|\[\.\.\.\]|…", q)]
    frags = [f for f in frags if len(f) >= 12]
    if len(frags) > 1 and all(f in s for f in frags):
        return SUPPORTED, 1.0, "verbatim (elided quote, all fragments found)"

    q = q.replace("...", " ").replace("…", " ")
    q = re.sub(r"\s+", " ", q).strip()
    if q in s:
        return SUPPORTED, 1.0, "verbatim"

    # Sliding-window fuzzy match
    best, win = 0.0, len(q)
    step = max(1, win // 4)
    for i in range(0, max(1, len(s) - win + 1), step):
        r = difflib.SequenceMatcher(None, q, s[i:i + win]).ratio()
        if r > best:
            best = r
            if best >= FUZZY_ACCEPT:
                break
    if best >= FUZZY_ACCEPT:
        return SUPPORTED, round(best, 3), "near-verbatim (minor edits)"
    if best >= FUZZY_PARTIAL:
        return UNSUPPORTED, round(best, 3), "paraphrased, not a quotation"
    return UNSUPPORTED, round(best, 3), "no matching text found in source"


# ─────────────────────────────────────────────────────────────────────────────
# Evidence extraction from free-text claims
# ─────────────────────────────────────────────────────────────────────────────
DOMAIN_RE = re.compile(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})\b", re.IGNORECASE)
COOKIE_RE = re.compile(r"['\"`]([A-Za-z0-9_\-]{2,40})['\"`]")
COUNT_RE = re.compile(r"\b(\d{1,4})\s+(?:third[- ]part(?:y|ies)|tracker|cookie|domain)", re.I)

# Words that look like domains but are prose/tooling references
DOMAIN_STOPWORDS = {"e.g", "i.e", "etc", "vs", "no.js", "art.13", "art.7"}

# Browser API names appear in fingerprinting findings ("HTMLCanvasElement.toDataURL",
# "navigator.getBattery") and match a naive domain pattern. They are legitimate
# evidence references, not fabricated domains.
JS_API_PREFIXES = ("navigator.", "document.", "window.", "htmlcanvaselement.",
                   "canvasrenderingcontext2d.", "webglrenderingcontext.",
                   "audiocontext.", "rtcpeerconnection.", "screen.", "performance.",
                   "crypto.", "intl.", "date.", "math.")
JS_API_SUFFIXES = (".todataurl", ".getcontext", ".getbattery", ".getusermedia",
                   ".createanalyser", ".createoscillator", ".measuretext",
                   ".getparameter", ".getsupportedextensions", ".enumeratedevices",
                   ".getclientrects", ".fonts", ".check", ".getcurrentposition")


def is_js_api(token: str) -> bool:
    t = token.lower()
    return t.startswith(JS_API_PREFIXES) or t.endswith(JS_API_SUFFIXES)


def evidence_universe(ev: dict, scanned_domain: str = "") -> dict:
    """All domains, cookie names and counts the evidence dict actually contains."""
    domains, cookies = set(), set()
    # The site's own domain is legitimate context, not a fabricated third party:
    # findings routinely say "independent.ie contacted X" or "the policy of
    # example.com". Without this the verifier flags the first party itself.
    for d in (scanned_domain, ev.get("domain", ""),
              urlparse(str(ev.get("scanned_url", ""))).netloc):
        if d:
            domains.add(norm(str(d)))
            domains.add(norm(str(d).replace("www.", "")))
    for d in ev.get("third_party_domains", []) or []:
        domains.add(norm(d))
    for r in ev.get("tracker_requests", []) or []:
        if isinstance(r, dict) and r.get("domain"):
            domains.add(norm(r["domain"]))
    for key in ("pre_consent_profiling_cookies", "js_set_profiling_cookies",
                "other_third_party_cookies"):
        for c in ev.get(key, []) or []:
            if isinstance(c, dict):
                if c.get("name"):
                    cookies.add(norm(c["name"]))
                if c.get("cookie_domain"):
                    domains.add(norm(str(c["cookie_domain"]).lstrip(".")))
    dva = ev.get("declared_vs_actual") or {}
    for key in ("observed_third_party_domains", "undeclared_domains",
                "declared_third_party_domains"):
        for d in dva.get(key, []) or []:
            domains.add(norm(d))
    for c in dva.get("undeclared_cookies", []) or []:
        cookies.add(norm(c))
    counts = {
        "third_party_domains": len(ev.get("third_party_domains", []) or []),
        "tracker_requests": len(ev.get("tracker_requests", []) or []),
        "profiling_cookies": len(ev.get("pre_consent_profiling_cookies", []) or []) +
                             len(ev.get("js_set_profiling_cookies", []) or []),
        "fingerprinting_alarms": len(ev.get("fingerprinting_alarms", []) or []),
    }
    return {"domains": domains, "cookies": cookies, "counts": counts,
            "raw": norm(json.dumps(ev))}


def check_behavioural_claim(claim: str, uni: dict) -> tuple[str, list[str], list[str]]:
    """Every domain/cookie named in the claim must exist in the evidence."""
    if not claim:
        return NA, [], []
    ok, bad = [], []
    for m in DOMAIN_RE.finditer(claim):
        d = norm(m.group(1))
        if d in DOMAIN_STOPWORDS or d.endswith((".py", ".json", ".md", ".har")):
            continue
        if is_js_api(d):          # fingerprinting API reference, not a domain
            ok.append(d)
            continue
        if any(d == k or d.endswith("." + k) or k.endswith("." + d) for k in uni["domains"]):
            ok.append(d)
        else:
            bad.append(f"domain '{d}' not in telemetry")
    for m in COOKIE_RE.finditer(claim):
        c = norm(m.group(1))
        if c in uni["cookies"]:
            ok.append(c)
        elif c not in uni["raw"]:
            bad.append(f"cookie '{c}' not in telemetry")
    for m in COUNT_RE.finditer(claim):
        n = int(m.group(1))
        if n not in uni["counts"].values() and str(n) not in uni["raw"]:
            bad.append(f"count '{n}' not corroborated by telemetry")
    if bad:
        return UNSUPPORTED, ok, bad
    return (SUPPORTED if ok else NA), ok, bad


# ─────────────────────────────────────────────────────────────────────────────
# Per-dimension verification
# ─────────────────────────────────────────────────────────────────────────────
def verify_dimension(d: dict, policy_text: str, uni: dict) -> dict:
    dim = d.get("dimension")
    verdict = d.get("verdict")
    breach = d.get("breach") or {}
    checks, issues = {}, []

    # Reports produced before retrieval provenance was recorded cannot be
    # checked for citation/quote grounding. Mark them unverifiable rather than
    # unsupported — otherwise a legacy report looks like a hallucinating one.
    legacy = "retrieved_articles" not in d and "rule_text" not in d

    # C1 — citation grounding
    retrieved = d.get("retrieved_articles") or []
    cited_art, cited_reg = breach.get("article"), breach.get("regulation")
    if not cited_art:
        checks["C1_citation"] = NA
    elif not retrieved:
        checks["C1_citation"] = NA
    else:
        base = re.match(r"\d+[A-Za-z]?", str(cited_art).replace("Article", "").strip())
        base = base.group(0) if base else str(cited_art)
        hit = any(str(r.get("article")) == base and
                  (not cited_reg or str(r.get("regulation")).upper() == str(cited_reg).upper())
                  for r in retrieved)
        checks["C1_citation"] = SUPPORTED if hit else UNSUPPORTED
        if not hit:
            got = ", ".join(f"{r.get('regulation')} {r.get('article')}" for r in retrieved)
            issues.append(f"C1: cited {cited_reg} Art {cited_art} but retrieval "
                          f"returned [{got}] — citation not grounded")

    # C2 — requirement quote verbatim in the rule text supplied
    if not d.get("rule_text"):
        checks["C2_requirement_quote"] = NA
    else:
        st, ratio, note = quote_supported(breach.get("requirement_text", ""), d["rule_text"])
        checks["C2_requirement_quote"] = st
        if st == UNSUPPORTED:
            issues.append(f"C2: requirement_text not found in retrieved law text "
                          f"({note}, best ratio {ratio})")

    # C3 — policy quote verbatim in scraped policy.
    # If no policy text is available to the verifier we cannot judge the quote;
    # that is a verification gap (often cross-domain policy hosting), not a
    # model error.
    if not policy_text:
        checks["C3_policy_quote"] = NA
        if d.get("policy_claim"):
            issues.append("C3: policy text unavailable to the verifier — quote "
                          "could not be checked (policy files not found for this domain)")
    else:
        st, ratio, note = quote_supported(d.get("policy_claim", ""), policy_text)
        checks["C3_policy_quote"] = st
        if st == UNSUPPORTED:
            issues.append(f"C3: policy_claim not found in scraped policy ({note}, "
                          f"best ratio {ratio})")

    # C4 — behavioural claims exist in telemetry
    st, ok, bad = check_behavioural_claim(d.get("behavioral_evidence", ""), uni)
    checks["C4_behavioural_claim"] = st
    for b in bad:
        issues.append(f"C4: {b}")

    # C5 — internal consistency
    cons = []
    if verdict == "NOT_ADDRESSED" and (breach.get("article") or d.get("score") is not None):
        cons.append("NOT_ADDRESSED carries a breach citation or a score")

    # Discrepancy-type rules differ by type. "Neglect" means the policy never
    # discloses the observed practice, so by definition there is no passage to
    # quote — demanding one is a category error. It does require that a policy
    # was available to read: non-disclosure cannot be asserted about a document
    # that was never retrieved. "Contrary" and "inadequate" both refer to
    # something the policy does say, so a quotation is required.
    disc = d.get("discrepancy_type")
    if disc == "neglect":
        if not d.get("behavioral_evidence"):
            cons.append("discrepancy_type 'neglect' asserted without behavioural evidence")
        elif not policy_text:
            cons.append("discrepancy_type 'neglect' asserted although no policy text was "
                        "retrieved — non-disclosure cannot be established from an unread document")
    elif disc in ("contrary", "inadequate"):
        if not (d.get("policy_claim") and d.get("behavioral_evidence")):
            cons.append(f"discrepancy_type '{disc}' asserted without both a policy "
                        "claim and behavioural evidence")
    band = VERDICT_BANDS.get(verdict)
    if band and isinstance(d.get("score"), int) and not (band[0] <= d["score"] <= band[1]):
        cons.append(f"score {d['score']} outside expected band {band} for {verdict}")
    if verdict in ("FAIL", "PARTIAL") and not d.get("policy_claim") and not d.get("behavioral_evidence"):
        cons.append(f"{verdict} asserted with neither a policy quote nor behavioural evidence")
    checks["C5_consistency"] = UNSUPPORTED if cons else SUPPORTED
    issues += [f"C5: {c}" for c in cons]

    return {"dimension": dim, "verdict": verdict, "score": d.get("score"),
            "confidence": d.get("confidence"), "checks": checks, "issues": issues,
            "legacy_no_provenance": legacy,
            "verifiable": not legacy,
            "grounded": not issues}


def verify_report(report_path: Path, evidence_path: Path | None,
                  policy_paths: list[Path]) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    ev = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path and evidence_path.exists() else {}
    uni = evidence_universe(ev, scanned_domain=report.get("domain", ""))

    if not policy_paths:
        for p in report.get("policies", []) or []:
            pp = Path(p)
            if not pp.is_absolute():
                pp = ROOT / p
            if pp.exists():
                policy_paths.append(pp)
    policy_text = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                            for p in policy_paths if p.exists())

    dims = [d for d in report.get("dimensions", []) if d.get("verdict") != "DRY_RUN"]
    results = [verify_dimension(d, policy_text, uni) for d in dims]

    tally = {}
    for r in results:
        for k, v in r["checks"].items():
            tally.setdefault(k, {SUPPORTED: 0, UNSUPPORTED: 0, NA: 0})[v] += 1
    n_unsupported = sum(1 for r in results if not r["grounded"])
    verifiable = [r for r in results if r["verifiable"]]
    v_unsupported = sum(1 for r in verifiable if not r["grounded"])

    return {
        "domain": report.get("domain"),
        "report": str(report_path),
        "model": report.get("model"),
        "legacy_report": len(verifiable) < len(results),
        "dimensions_checked": len(results),
        "dimensions_verifiable": len(verifiable),
        "dimensions_fully_grounded": len(results) - n_unsupported,
        "dimensions_with_issues": n_unsupported,
        # Headline metric: computed over dimensions that carry retrieval
        # provenance, so a pre-provenance report does not read as ungrounded.
        "grounding_rate": round((len(verifiable) - v_unsupported) / len(verifiable), 3) if verifiable else None,
        "grounding_rate_all": round((len(results) - n_unsupported) / len(results), 3) if results else None,
        "policy_text_available": bool(policy_text),
        "evidence_available": bool(ev),
        "check_tally": tally,
        "dimensions": results,
    }


def print_summary(v: dict):
    print(f"\nGROUNDING VERIFICATION — {v['domain']}")
    print(f"  report: {Path(v['report']).name}   model: {v['model']}")
    print(f"  policy text available: {v['policy_text_available']}   "
          f"evidence available: {v['evidence_available']}")
    print(f"  dimensions checked: {v['dimensions_checked']}   "
          f"fully grounded: {v['dimensions_fully_grounded']}   "
          f"with issues: {v['dimensions_with_issues']}")
    if v.get("legacy_report"):
        print(f"  [!] {v['dimensions_checked'] - v['dimensions_verifiable']} dimension(s) "
              "predate retrieval provenance — citation/quote grounding could not be "
              "checked. Re-score with --force for a full verification.")
    if v["grounding_rate"] is not None:
        print(f"  grounding rate: {v['grounding_rate']:.0%} "
              f"(over {v['dimensions_verifiable']} verifiable dimension(s))")
    print("\n  per-check tally (supported / unsupported / n-a):")
    for k, t in v["check_tally"].items():
        print(f"    {k:24s} {t[SUPPORTED]:3d} / {t[UNSUPPORTED]:3d} / {t[NA]:3d}")
    flagged = [d for d in v["dimensions"] if d["issues"]]
    if flagged:
        print("\n  FLAGGED CLAIMS (potential hallucinations / inconsistencies):")
        for d in flagged:
            print(f"    - {d['dimension']} [{d['verdict']}]")
            for i in d["issues"]:
                print(f"        {i}")
    else:
        print("\n  No unsupported claims found: every citation, quote and "
              "behavioural claim traces to its source artefact.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Verify that a compliance report is grounded in its inputs.")
    ap.add_argument("report")
    ap.add_argument("--evidence", help="har_extractor evidence JSON for this scan")
    ap.add_argument("--policy", action="append", default=[], help="policy .md (repeatable)")
    ap.add_argument("--json", help="write the verification result to this path")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any claim is unsupported")
    args = ap.parse_args()

    v = verify_report(Path(args.report),
                      Path(args.evidence) if args.evidence else None,
                      [Path(p) for p in args.policy])
    print_summary(v)
    if args.json:
        Path(args.json).write_text(json.dumps(v, indent=2), encoding="utf-8")
        print(f"\n[✓] Verification written to {args.json}")
    if args.strict and v["dimensions_with_issues"]:
        sys.exit(1)
