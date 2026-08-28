"""
Batch audit harness — Phase 6 (evaluation)
LLM-Driven Privacy Compliance Framework
Author: Aaron Joseph Jean — 25233118

Runs the full pipeline over a list of websites, verifies every report against
its own telemetry, and produces the summary tables used in the evaluation
chapter. Designed to be interrupted and resumed: a site whose report already
exists is skipped unless --force is given.

Per site it records: capture health (requests, UI elements, blocked?), policy
retrieval success, per-dimension verdicts, overall score, wall-clock time, and
the grounding-verification result from evaluation/verify_report.py.

Usage:
    python3 evaluation/batch_audit.py                      # all sites, demo preset
    python3 evaluation/batch_audit.py --sites evaluation/sites.txt \
        --preset behavioural --model gpt-4o-mini --limit 5
    python3 evaluation/batch_audit.py --summarise-only     # rebuild tables only

Outputs (evaluation/results/):
    batch_results.csv        one row per site
    batch_results.json       full detail incl. per-dimension verdicts
    summary.md               markdown tables for the paper
    verification/<domain>.json
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent


def _interpreter() -> str:
    """Prefer the project venv, whatever interpreter launched this script.

    Running `python3 evaluation/batch_audit.py` outside the venv otherwise
    spawns every pipeline stage with the system Python, which lacks
    llama_index / chromadb / playwright and fails at the scoring stage.
    """
    for cand in (ROOT / "venv" / "bin" / "python3", ROOT / "venv" / "bin" / "python",
                 ROOT / ".venv" / "bin" / "python3"):
        if cand.exists():
            return str(cand)
    return sys.executable


PY = _interpreter()
OUT = ROOT / "evaluation" / "results"
VERIF = OUT / "verification"

sys.path.insert(0, str(ROOT))

# Jurisdiction → applicable instruments.
#
# The ePrivacy Directive is transposed nationally, so the cookie-consent rule
# differs by country even though GDPR applies EU-wide:
#   IE  S.I. 336/2011 Reg 5(3)   (enforced by the DPC)
#   UK  PECR 2003 Reg 6
#   IN  DPDP Act 2023
# Scoring an Irish site against PECR cites the wrong instrument, which was the
# case in the first batch and is corrected here.
DEFAULT_REGS = ["__by_jurisdiction__"]

JURISDICTION_REGS = {
    "IE": ["GDPR", "EPRIVACY-IE"],
    "UK": ["GDPR", "PECR"],
    "EU": ["GDPR"],
    "IN": ["DPDP"],
    "US": ["CCPA"],
}

PRESETS = {
    "demo": ["pre_consent_tracking", "tracking_without_consent", "disclosure_of_third_parties"],
    "behavioural": ["pre_consent_tracking", "consent_mechanism_validity", "tracking_without_consent",
                    "disclosure_of_data_collected", "disclosure_of_third_parties",
                    "cookie_retention_period", "cross_border_transfers", "data_minimisation"],
    "all": [],
}


def log(msg):
    print(msg, flush=True)


LOGS = ROOT / "evaluation" / "results" / "logs"


def run(args, timeout=600, log_name: str | None = None) -> tuple[bool, str]:
    """Run a pipeline CLI. Full output is always written to
    evaluation/results/logs/<log_name>.log so failures can be diagnosed."""
    try:
        p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        ok = p.returncode == 0
    except subprocess.TimeoutExpired:
        out, ok = f"TIMEOUT after {timeout}s", False
    except Exception as e:
        out, ok = str(e), False

    if log_name:
        LOGS.mkdir(parents=True, exist_ok=True)
        with open(LOGS / f"{log_name}.log", "a", encoding="utf-8") as f:
            f.write(f"\n$ {' '.join(str(a) for a in args)}\n{out}\n")
    if not ok:
        tail = [l for l in out.strip().splitlines() if l.strip()][-12:]
        log("      ┌─ command failed, last lines of output:")
        for l in tail:
            log(f"      │ {l[:160]}")
        log("      └─ full log: evaluation/results/logs/" + (log_name or "?") + ".log")
    return ok, out


def newest(pattern: str) -> Path | None:
    files = sorted(glob.glob(str(ROOT / pattern)), key=os.path.getmtime)
    return Path(files[-1]) if files else None


def read_sites(path: Path) -> list[dict]:
    sites = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        sites.append({"url": parts[0],
                      "sector": parts[1] if len(parts) > 1 else "unknown",
                      "jurisdiction": parts[2] if len(parts) > 2 else "?"})
    return sites


def capture_health(tele: Path | None) -> dict:
    if not tele or not tele.exists():
        return {"requests": 0, "ui_elements": 0, "blocked": True}
    try:
        t = json.loads(tele.read_text(encoding="utf-8"))
        r = t.get("observed_behavior", {}).get("network_summary", {}).get("total_requests", 0)
        u = t.get("visual_evidence", {}).get("interactable_elements", {}).get("total", 0)
        return {"requests": r, "ui_elements": u, "blocked": (r < 10 or u == 0)}
    except Exception:
        return {"requests": 0, "ui_elements": 0, "blocked": True}


POLICY_MAP = ROOT / "evaluation" / "policy_map.json"


def find_policies(domain: str) -> list[Path]:
    """Delegates to ingestion/policy_lookup.py — the single source of truth,
    shared with the frontend."""
    from ingestion.policy_lookup import find_policies as _find
    return _find(domain, verbose=True)


def audit_site(site: dict, preset: str, model: str, regulations: list[str],
               force: bool) -> dict:
    url = site["url"]
    domain = urlparse(url).netloc or url
    t0 = time.time()
    rec = {**site, "domain": domain, "scanned_at": datetime.now(timezone.utc).isoformat(),
           "status": "", "notes": ""}

    existing = newest(f"compliance_reports/{domain}_*_report.json")
    if existing and not force:
        log(f"  [skip] report exists: {existing.name}")
        rec["status"] = "reused"
    else:
        log(f"  [1/4] telemetry …")
        ok, out = run([PY, "telemetry_collector.py", url], timeout=480, log_name=domain)
        if not ok:
            rec.update(status="collector_failed", notes=out.strip().splitlines()[-1][:200] if out else "")
            return rec

    har = newest(f"telemetry_output/{domain}_*.har")
    tele = newest(f"telemetry_output/{domain}_*_telemetry.json")
    health = capture_health(tele)
    rec.update(requests=health["requests"], ui_elements=health["ui_elements"])

    if health["blocked"]:
        rec.update(status="blocked", notes="degenerate capture (bot protection suspected)")
        log(f"  [!] blocked — {health['requests']} requests, {health['ui_elements']} UI elements")
        return rec

    if rec["status"] != "reused":
        log(f"  [2/4] evidence …")
        ev_path = ROOT / "telemetry_output" / f"{domain}_evidence.json"
        run([PY, "ingestion/har_extractor.py", str(har), "--telemetry", str(tele),
             "--json", str(ev_path)], timeout=180, log_name=domain)

        if not find_policies(domain):
            log(f"  [3/4] policies …")
            run([PY, "policy_scraper_2.py", url, str(tele)], timeout=300, log_name=domain)

        policies = find_policies(domain)
        rec["policies_found"] = len(policies)
        log(f"  [4/4] scoring ({len(policies)} policy file(s)) …")
        cmd = [PY, "rag/scorer.py", "--domain", domain, "--har", str(har),
               "--telemetry", str(tele), "--model", model]
        for p in policies:
            cmd += ["--policy", str(p)]
        if PRESETS.get(preset):
            cmd += ["--dimensions", *PRESETS[preset]]
        if regulations:
            cmd += ["--regulations", *regulations]
        ok, out = run(cmd, timeout=900, log_name=domain)
        if not ok:
            rec.update(status="scorer_failed", notes=out.strip().splitlines()[-1][:200] if out else "")
            return rec
    else:
        rec["policies_found"] = len(find_policies(domain))

    report_path = newest(f"compliance_reports/{domain}_*_report.json")
    if not report_path:
        rec.update(status="no_report")
        return rec
    report = json.loads(report_path.read_text(encoding="utf-8"))
    dims = [d for d in report.get("dimensions", []) if d.get("verdict") != "DRY_RUN"]
    rec.update(
        status=rec["status"] or "ok",
        overall_score=report.get("overall_score"),
        overall_verdict=report.get("overall_verdict"),
        n_dimensions=len(dims),
        n_fail=sum(1 for d in dims if d["verdict"] == "FAIL"),
        n_partial=sum(1 for d in dims if d["verdict"] == "PARTIAL"),
        n_pass=sum(1 for d in dims if d["verdict"] == "PASS"),
        n_not_addressed=sum(1 for d in dims if d["verdict"] == "NOT_ADDRESSED"),
        report=str(report_path.relative_to(ROOT)),
        verdicts={d["dimension"]: d["verdict"] for d in dims},
    )
    if rec["status"] == "":
        rec["status"] = "ok"

    # Grounding verification
    from evaluation.verify_report import verify_report
    ev_path = ROOT / "telemetry_output" / f"{domain}_evidence.json"
    try:
        v = verify_report(report_path, ev_path if ev_path.exists() else None, find_policies(domain))
        VERIF.mkdir(parents=True, exist_ok=True)
        (VERIF / f"{domain}.json").write_text(json.dumps(v, indent=2), encoding="utf-8")
        rec.update(grounding_rate=v["grounding_rate"],
                   dims_with_issues=v["dimensions_with_issues"],
                   issues=[i for d in v["dimensions"] for i in d["issues"]])
        log(f"  [✓] {rec['overall_verdict']} ({rec['overall_score']}) · "
            f"grounding {v['grounding_rate']}")
    except Exception as e:
        rec["notes"] = f"verification failed: {e}"

    rec["seconds"] = round(time.time() - t0, 1)
    return rec


# ─────────────────────────────────────────────────────────────────────────────
# Summaries
# ─────────────────────────────────────────────────────────────────────────────
def summarise(records: list[dict]) -> str:
    ok = [r for r in records if r.get("status") in ("ok", "reused") and r.get("overall_score") is not None]
    blocked = [r for r in records if r.get("status") == "blocked"]
    failed = [r for r in records if r.get("status") in ("collector_failed", "scorer_failed", "no_report")]

    L = ["# Batch audit summary", "",
         f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
         f"{len(records)} sites attempted · {len(ok)} scored · {len(blocked)} blocked · {len(failed)} failed",
         ""]

    L += ["## Per-site results", "",
          "| Site | Sector | Juris. | Status | Score | Verdict | FAIL | PARTIAL | N/A | Policies | Grounding |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in records:
        L.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            r.get("domain", ""), r.get("sector", ""), r.get("jurisdiction", ""),
            r.get("status", ""),
            r.get("overall_score", "—"), r.get("overall_verdict", "—"),
            r.get("n_fail", "—"), r.get("n_partial", "—"), r.get("n_not_addressed", "—"),
            r.get("policies_found", "—"),
            f"{r['grounding_rate']:.0%}" if r.get("grounding_rate") is not None else "—"))
    L.append("")

    # Sector aggregation
    L += ["## By sector", "", "| Sector | Sites scored | Mean score | FAIL verdicts / dimension |", "|---|---|---|---|"]
    sectors = {}
    for r in ok:
        sectors.setdefault(r["sector"], []).append(r)
    for sec, rs in sorted(sectors.items(), key=lambda kv: -sum(x["overall_score"] for x in kv[1]) / len(kv[1])):
        mean = sum(x["overall_score"] for x in rs) / len(rs)
        fails = sum(x.get("n_fail", 0) for x in rs)
        dims = sum(x.get("n_dimensions", 0) for x in rs)
        L.append(f"| {sec} | {len(rs)} | {mean:.1f} | {fails}/{dims} "
                 f"({(fails/dims*100 if dims else 0):.0f}%) |")
    L.append("")

    # Policy availability confound — the single most important control:
    # if sites whose policies we failed to scrape score systematically lower,
    # the score is partly measuring our scraper, not the site.
    byp: dict[int, list] = {}
    for r in ok:
        byp.setdefault(r.get("policies_found", 0), []).append(r)
    if len(byp) > 1:
        L += ["## Confound check: score vs policy availability", "",
              "| Policy files retrieved | Sites | Mean score | Mean grounding |",
              "|---|---|---|---|"]
        for k in sorted(byp):
            rs = byp[k]
            m = sum(x["overall_score"] for x in rs) / len(rs)
            g = [x["grounding_rate"] for x in rs if x.get("grounding_rate") is not None]
            L.append(f"| {k} | {len(rs)} | {m:.1f} | "
                     f"{(sum(g)/len(g)*100 if g else 0):.0f}% |")
        zero = byp.get(0, [])
        some = [r for k, v in byp.items() if k > 0 for r in v]
        if zero and some:
            mz = sum(r["overall_score"] for r in zero) / len(zero)
            ms = sum(r["overall_score"] for r in some) / len(some)
            L += ["", f"Sites with no policy retrieved score **{ms - mz:.0f} points lower** "
                      f"on average ({mz:.1f} vs {ms:.1f}). Scores for those sites reflect "
                      "the auditing pipeline's retrieval coverage as much as the site's "
                      "compliance, and must be reported separately.", ""]

    # Per-dimension behaviour across sites — exposes dimensions that always
    # return the same verdict (low information) and score clustering.
    perdim: dict[str, list] = {}
    for r in ok:
        for dim, verdict in (r.get("verdicts") or {}).items():
            perdim.setdefault(dim, []).append(verdict)
    if perdim:
        L += ["## Per-dimension verdict distribution", "",
              "| Dimension | FAIL | PARTIAL | PASS | NOT_ADDRESSED | distinct verdicts |",
              "|---|---|---|---|---|---|"]
        for dim, vs in sorted(perdim.items()):
            L.append(f"| {dim} | {vs.count('FAIL')} | {vs.count('PARTIAL')} | "
                     f"{vs.count('PASS')} | {vs.count('NOT_ADDRESSED')} | {len(set(vs))} |")
        L += ["", "A dimension with only one distinct verdict across all sites carries "
                  "little discriminating information and should be examined.", ""]

    scores = [r["overall_score"] for r in ok]
    if scores:
        L += ["## Score distribution", "",
              f"- range: **{min(scores)}–{max(scores)}** · mean **{sum(scores)/len(scores):.1f}** "
              f"· distinct values: **{len(set(scores))}** of {len(scores)} sites", ""]
        hist = {}
        for s in scores:
            hist[s] = hist.get(s, 0) + 1
        L += ["| Overall score | Sites |", "|---|---|"]
        for s in sorted(hist):
            L.append(f"| {s} | {hist[s]} |")
        L += ["", "Clustering on round values (0/25/50/75) indicates the model is "
                  "anchoring on rubric points rather than using a continuous scale — "
                  "report verdicts as ordinal, not scores as interval data.", ""]

    # Grounding / hallucination
    gr = [r for r in ok if r.get("grounding_rate") is not None]
    if gr:
        mean_g = sum(r["grounding_rate"] for r in gr) / len(gr)
        total_issues = sum(len(r.get("issues", [])) for r in gr)
        L += ["## Grounding verification (hallucination check)", "",
              f"- Reports verified: **{len(gr)}**",
              f"- Mean grounding rate (dimensions with every claim traced to source): **{mean_g:.1%}**",
              f"- Total unsupported claims flagged: **{total_issues}**", ""]
        buckets = {}
        for r in gr:
            for i in r.get("issues", []):
                buckets.setdefault(i.split(":")[0], []).append((r["domain"], i))
        if buckets:
            L += ["| Check | Flags | Example |", "|---|---|---|"]
            names = {"C1": "citation not retrieved", "C2": "requirement quote not verbatim",
                     "C3": "policy quote not found", "C4": "behavioural claim not in telemetry",
                     "C5": "internal inconsistency"}
            for k in sorted(buckets):
                dom, ex = buckets[k][0]
                L.append(f"| {k} — {names.get(k, '')} | {len(buckets[k])} | {dom}: {ex[:110]} |")
            L.append("")

        # Attribution: a flag is not automatically model fabrication. Split by
        # the component actually responsible so the limitations section can
        # separate "the model invented something" from "we failed to fetch it".
        cats = {"fabricated": 0, "unlocatable": 0, "paraphrase": 0,
                "missing_input": 0, "inconsistency": 0}
        for r in gr:
            for i in r.get("issues", []):
                if "not in telemetry" in i or "not corroborated" in i:
                    cats["fabricated"] += 1          # C4: invented behavioural claim
                elif "paraphrased" in i:
                    cats["paraphrase"] += 1          # C2/C3: right idea, not a quote
                elif "no matching text found" in i:
                    cats["unlocatable"] += 1         # C2/C3: quote not in the source at all
                elif ("no policy text was retrieved" in i or "unavailable" in i
                      or "could not be checked" in i):
                    cats["missing_input"] += 1       # reasoning about an unread document
                else:
                    cats["inconsistency"] += 1       # C1/C5 structural faults
        L += ["**Attribution of flags**", "",
              "| Cause | Flags | Interpretation |", "|---|---|---|",
              f"| Fabricated behavioural claim | {cats['fabricated']} | a domain, cookie or count that is not in the telemetry |",
              f"| Unlocatable quotation | {cats['unlocatable']} | quoted text not found in the source document |",
              f"| Paraphrase instead of quotation | {cats['paraphrase']} | substantively correct but not copied verbatim |",
              f"| Over-claim on a missing input | {cats['missing_input']} | non-disclosure asserted about a policy that was never retrieved |",
              f"| Structural inconsistency | {cats['inconsistency']} | citation or schema rule violated |",
              ""]

    if blocked:
        L += ["## Sites that could not be captured", "",
              "| Site | Requests | UI elements |", "|---|---|---|"]
        for r in blocked:
            L.append(f"| {r['domain']} | {r.get('requests', 0)} | {r.get('ui_elements', 0)} |")
        L += ["", f"Capture failure rate: **{len(blocked)}/{len(records)} "
                  f"({len(blocked)/len(records)*100:.0f}%)** — bot protection is the "
                  "principal coverage limitation.", ""]
    return "\n".join(L)


def write_outputs(records: list[dict]):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "batch_results.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    cols = ["domain", "sector", "jurisdiction", "status", "requests", "ui_elements",
            "policies_found", "overall_score", "overall_verdict", "n_dimensions",
            "n_fail", "n_partial", "n_pass", "n_not_addressed", "grounding_rate",
            "dims_with_issues", "seconds", "notes"]
    with open(OUT / "batch_results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow(r)
    (OUT / "summary.md").write_text(summarise(records), encoding="utf-8")
    log(f"\n[✓] {OUT/'batch_results.csv'}\n[✓] {OUT/'summary.md'}")


def preflight(model: str) -> bool:
    """Check the environment before spending time and API credit.
    Catches the common failure: running outside the venv, no API key, or an
    empty vector store."""
    log(f"Preflight (interpreter: {PY})")
    ok = True

    probe = ("import importlib,sys; "
             "missing=[m for m in ['llama_index','chromadb','playwright','bs4'] "
             "if importlib.util.find_spec(m) is None); print(','.join(missing))")
    try:
        p = subprocess.run([PY, "-c", probe], capture_output=True, text=True, timeout=120)
        missing = (p.stdout or "").strip()
    except Exception as e:
        missing, ok = f"probe failed: {e}", False
    if missing:
        log(f"  [x] missing packages in that interpreter: {missing}")
        log("      fix: source venv/bin/activate && pip install -r requirements.txt")
        ok = False
    else:
        log("  [ok] pipeline packages present")

    key = "ANTHROPIC_API_KEY" if model.startswith("claude") else "OPENAI_API_KEY"
    if os.environ.get(key):
        log(f"  [ok] {key} set")
    else:
        log(f"  [x] {key} not set in this shell — scoring will fail")
        ok = False

    db = ROOT / "chroma_db"
    if db.exists() and any(db.iterdir()):
        log("  [ok] vector store present")
    else:
        log("  [x] chroma_db missing or empty — run ingestion/ingest.py first")
        ok = False

    log("")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run and verify audits over a list of sites.")
    ap.add_argument("--sites", default="evaluation/sites.txt")
    ap.add_argument("--preset", default="demo", choices=list(PRESETS))
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--regulations", nargs="*", default=DEFAULT_REGS,
                    help="override the per-jurisdiction default instruments")
    ap.add_argument("--limit", type=int, help="only the first N sites")
    ap.add_argument("--force", action="store_true", help="re-scan even if a report exists")
    ap.add_argument("--summarise-only", action="store_true",
                    help="rebuild tables from evaluation/results/batch_results.json")
    ap.add_argument("--reverify", action="store_true",
                    help="re-run grounding verification over existing reports (offline, no API calls)")
    args = ap.parse_args()

    if args.reverify:
        # Re-run grounding verification over the existing reports. Offline and
        # free: no collection, no scoring, no API calls. Use after changing
        # verify_report.py so the numbers reflect the current checks.
        from evaluation.verify_report import verify_report
        recs = json.loads((OUT / "batch_results.json").read_text(encoding="utf-8"))
        VERIF.mkdir(parents=True, exist_ok=True)
        for r in recs:
            if not r.get("report"):
                continue
            dom = r["domain"]
            ev = ROOT / "telemetry_output" / f"{dom}_evidence.json"
            v = verify_report(ROOT / r["report"], ev if ev.exists() else None,
                              find_policies(dom))
            (VERIF / f"{dom}.json").write_text(json.dumps(v, indent=2), encoding="utf-8")
            r["grounding_rate"] = v["grounding_rate"]
            r["dims_with_issues"] = v["dimensions_with_issues"]
            r["issues"] = [i for d in v["dimensions"] for i in d["issues"]]
            log(f"  {dom:30s} grounding {v['grounding_rate']}  issues {v['dimensions_with_issues']}")
        write_outputs(recs)
        sys.exit(0)

    if args.summarise_only:
        recs = json.loads((OUT / "batch_results.json").read_text(encoding="utf-8"))
        write_outputs(recs)
        sys.exit(0)

    if not preflight(args.model):
        sys.exit(2)

    sites = read_sites(ROOT / args.sites)
    if args.limit:
        sites = sites[:args.limit]
    log(f"Auditing {len(sites)} site(s) · preset={args.preset} · model={args.model}\n")

    records = []
    for i, site in enumerate(sites, 1):
        log(f"[{i}/{len(sites)}] {site['url']}  ({site['sector']}, {site['jurisdiction']})")
        # Jurisdiction determines the applicable instruments unless the user
        # has overridden --regulations explicitly.
        juris = site["jurisdiction"].upper()
        if args.regulations == DEFAULT_REGS:
            regs = JURISDICTION_REGS.get(juris, ["GDPR"])
            log(f"  [i] {juris}: scoring against {', '.join(regs)}")
        else:
            regs = list(args.regulations)
        try:
            records.append(audit_site(site, args.preset, args.model, regs, args.force))
        except KeyboardInterrupt:
            log("\ninterrupted — writing partial results")
            break
        except Exception as e:
            log(f"  [x] {e}")
            records.append({**site, "status": "error", "notes": str(e)[:200]})
        write_outputs(records)   # checkpoint after every site
    log("\n" + summarise(records))
